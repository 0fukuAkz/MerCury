"""Tests for logging context utilities."""

import pytest
import logging
from unittest.mock import patch, Mock
from mercury.utils.logging_context import (
    ContextLogger,
    get_context_logger,
    log_email_operation,
    EmailOperationContext,
    log_error_with_context,
    configure_structured_logging,
)


# Helpers
class CustomError(Exception):
    def __init__(self, msg, details=None):
        super().__init__(msg)
        self.details = details


# Tests
def test_context_logger_init():
    logger = ContextLogger("test", {"a": 1})
    assert logger.logger.name == "test"
    assert logger.context == {"a": 1}


def test_context_logger_formatting():
    logger = ContextLogger("test", {"user": "u1"})
    # Mock internal logger
    logger.logger = Mock()

    logger.info("Message")
    # _format_message includes context in the message string: "Message | user=u1"
    # extra passed to logger.info matches **kwargs passed to method (empty here)

    args, kwargs = logger.logger.info.call_args
    assert "Message" in args[0]
    assert "user=u1" in args[0]
    assert kwargs["extra"] == {}  # Correct: context is IN string, not extra dict here

    logger.info("Message", extra_field="val")

    args, kwargs = logger.logger.info.call_args
    assert "Message" in args[0]
    assert "extra_field=val" in args[0]
    # Here extra should contain passed kwargs
    assert kwargs["extra"] == {"extra_field": "val"}


def test_context_logger_levels():
    logger = ContextLogger("test")
    logger.logger = Mock()

    logger.debug("Debug")
    logger.logger.debug.assert_called()

    logger.warning("Warn")
    logger.logger.warning.assert_called()

    logger.critical("Crit")
    logger.logger.critical.assert_called()


def test_context_logger_error_handling():
    logger = ContextLogger("test")
    logger.logger = Mock()

    err = CustomError("fail", details={"code": 500})
    logger.error("Error happened", error=err, extra_k="v")

    call_args = logger.logger.error.call_args
    assert call_args[1]["exc_info"] is True
    extra = call_args[1]["extra"]
    assert extra["error_type"] == "CustomError"
    assert extra["error_msg"] == "fail"
    assert extra["error_details"] == {"code": 500}
    assert extra["extra_k"] == "v"


def test_context_logger_with_context():
    l1 = ContextLogger("test", {"a": 1})
    l2 = l1.with_context(b=2)

    assert l1.context == {"a": 1}
    assert l2.context == {"a": 1, "b": 2}
    assert l2.logger.name == "test"


def test_get_context_logger():
    l = get_context_logger("my_logger", x=10)
    assert isinstance(l, ContextLogger)
    assert l.logger.name == "my_logger"
    assert l.context == {"x": 10}


@pytest.mark.asyncio
async def test_log_email_operation_decorator():
    @log_email_operation("send_mail")
    async def sample_func(recipient, **kwargs):
        if recipient == "fail@test":
            raise ValueError("Failed")
        return "ok"

    # Mock get_context_logger to assert calls
    with patch("mercury.utils.logging_context.get_context_logger") as mock_get:
        mock_logger = Mock()
        mock_get.return_value = mock_logger

        # Success case
        await sample_func(recipient="user@test", correlation_id="123")

        # Verify calls
        assert mock_logger.info.call_count == 2  # Start, End
        # Start
        start_call = mock_logger.info.call_args_list[0]
        assert "Starting send_mail" in start_call[0][0]
        assert start_call[1]["recipient"] == "user@test"
        assert start_call[1]["correlation_id"] == "123"

        # Fail case
        with pytest.raises(ValueError):
            await sample_func(recipient="fail@test")

        # Verify error log
        assert mock_logger.error.call_count == 1
        err_call = mock_logger.error.call_args
        assert "Failed send_mail" in err_call[0][0]
        assert isinstance(err_call[1]["error"], ValueError)


def test_email_operation_context_success():
    with patch("mercury.utils.logging_context.get_context_logger") as mock_get:
        mock_logger = Mock()
        mock_get.return_value = mock_logger

        with EmailOperationContext("op", recipient="r", campaign_id=1) as log:
            assert log == mock_logger
            mock_logger.info.assert_called_with("▶️  Starting op")

        # Exit success
        end_call = mock_logger.info.call_args_list[-1]
        assert "✅ Completed op" in end_call[0][0]
        assert "duration_seconds" in end_call[1]


def test_email_operation_context_failure():
    with patch("mercury.utils.logging_context.get_context_logger") as mock_get:
        mock_logger = Mock()
        mock_get.return_value = mock_logger

        with pytest.raises(ValueError):
            with EmailOperationContext("op"):
                raise ValueError("Oops")

        # Exit failure
        err_call = mock_logger.error.call_args
        assert "❌ Failed op" in err_call[0][0]
        assert isinstance(err_call[1]["error"], ValueError)


def test_log_error_with_context_helper():
    mock_log = Mock()
    err = ValueError("bad")

    data = log_error_with_context(mock_log, "Msg", err, ctx="1")

    mock_log.error.assert_called()
    assert data["error_context_msg"] == "Msg"
    assert data["error_msg"] == "bad"
    assert data["ctx"] == "1"


def test_configure_structured_logging(tmp_path):
    log_file = tmp_path / "app.log"

    # Reset logging handlers to ensure clean state
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()

    configure_structured_logging(log_level="DEBUG", log_file=str(log_file), json_logs=True)

    logger = logging.getLogger("test_structured")
    logger.propagate = True  # Ensure propagation
    logger.info("Test Log")

    # Shutdown logging system to flush everything
    logging.shutdown()

    if not log_file.exists():
        pytest.fail("Log file not created")

    content = log_file.read_text()
    assert '"message": "Test Log"' in content
    assert '"level": "INFO"' in content
