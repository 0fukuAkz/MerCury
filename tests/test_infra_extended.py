
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from mercury.services.smtp_service import SMTPService
from mercury.utils.async_io import (
    async_write_line, async_write_file, async_read_file, 
    async_iter_lines, AsyncFileLogger
)
from mercury.engine.connection_pool import SMTPConnectionPool

class TestSMTPServiceExtended:
    
    @pytest.fixture
    def mock_repo(self):
        with patch('mercury.services.smtp_service.SMTPRepository') as mock:
            yield mock

    @pytest.fixture
    def mock_session(self):
        with patch('mercury.services.smtp_service.get_session_direct') as mock:
            msg = MagicMock()
            mock.return_value = msg
            yield msg

    def test_load_from_config(self):
        service = SMTPService()
        configs = [
            {'name': 's1', 'host': 'h1', 'port': 25},
            {'name': 's2', 'host': 'h2', 'port': 587}
        ]
        
        loaded = service.load_from_config(configs)
        assert len(loaded) == 2
        assert loaded[0].name == 's1'
        assert loaded[1].host == 'h2'

    def test_get_connection_pool_no_config(self):
        service = SMTPService()
        with pytest.raises(RuntimeError):
            service.get_connection_pool()

    def test_get_connection_pool_lazy_init(self):
        service = SMTPService()
        service.load_from_config([{'name': 's1', 'host': 'h1'}])
        
        pool1 = service.get_connection_pool()
        pool2 = service.get_connection_pool()
        
        assert pool1 is pool2
        assert isinstance(pool1, SMTPConnectionPool)

    @pytest.mark.asyncio
    async def test_test_connection_success_starttls_no_double_ehlo(self):
        """For the STARTTLS path, we MUST NOT issue an explicit EHLO
        after starttls() — aiosmtplib's starttls() already sends one
        internally (RFC 3207). The previous code sent a second EHLO,
        which AWS SES tolerated but iCloud and strict Postfix configs
        rejected with 503. Regression guard for the iCloud-fails-but-
        AWS-passes bug.
        """
        # use_auth=False so the misconfigured_auth precondition doesn't
        # short-circuit before we reach the mocked aiosmtplib client.
        # Default tls_mode is 'starttls' (the from_dict default).
        service = SMTPService()
        service.load_from_config([{'name': 's1', 'host': 'h1', 'use_auth': False}])

        with patch('aiosmtplib.SMTP') as MockSMTP:
            client = AsyncMock()
            MockSMTP.return_value = client

            result = await service.test_connection('s1')

            assert result['success'] is True
            client.connect.assert_awaited_once()
            client.starttls.assert_awaited_once()
            # The fix: do NOT call ehlo() explicitly — starttls()
            # already handled it. A second EHLO is what trips iCloud.
            client.ehlo.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_test_connection_success_no_tls_does_explicit_ehlo(self):
        """For tls_mode='none' there's no STARTTLS upgrade to trigger
        an implicit EHLO, so the code path MUST issue one explicitly.
        Validates the else branch added alongside the iCloud fix.
        """
        service = SMTPService()
        service.load_from_config([
            {'name': 's1', 'host': 'h1', 'use_auth': False, 'tls_mode': 'none'},
        ])

        with patch('aiosmtplib.SMTP') as MockSMTP:
            client = AsyncMock()
            MockSMTP.return_value = client

            result = await service.test_connection('s1')

            assert result['success'] is True
            client.connect.assert_awaited_once()
            client.starttls.assert_not_awaited()
            client.ehlo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        service = SMTPService()
        service.load_from_config([{'name': 's1', 'host': 'h1', 'use_auth': False}])

        with patch('aiosmtplib.SMTP') as MockSMTP:
            client = AsyncMock()
            client.connect.side_effect = Exception("Connection failed")
            MockSMTP.return_value = client

            result = await service.test_connection('s1')

            # The service sanitizes raw str(e) before returning (banners
            # / internal hostnames must not leak through REST). We only assert
            # the failure was caught and reported.
            assert result['success'] is False
            assert result.get('error_type') == 'unknown'

    @pytest.mark.asyncio
    async def test_test_connection_dns_failure_is_classified(self):
        """SMTPConnectError carrying a 'nodename nor servname provided'
        message must be classified as dns_failure (not generic tcp_failed)
        so the operator gets the DNS-specific hint pointing them at
        their resolver. Regression guard for the iCloud-smtp-fails-but-
        AWS-passes bug: consumer routers that return SERVFAIL for
        smtp.mail.me.com while resolving AWS hosts fine.
        """
        import aiosmtplib
        service = SMTPService()
        service.load_from_config([
            {'name': 'icloud', 'host': 'smtp.mail.me.com', 'port': 587,
             'use_auth': False, 'tls_mode': 'starttls'},
        ])

        with patch('aiosmtplib.SMTP') as MockSMTP:
            client = AsyncMock()
            # Real macOS getaddrinfo error text aiosmtplib bubbles up.
            client.connect.side_effect = aiosmtplib.SMTPConnectError(
                'Error connecting to smtp.mail.me.com on port 587: '
                '[Errno 8] nodename nor servname provided, or not known'
            )
            MockSMTP.return_value = client

            result = await service.test_connection('icloud')

            assert result['success'] is False
            assert result['error_type'] == 'dns_failure'
            # The hint must mention the resolver-change workaround;
            # that's the actually-fixes-the-problem step.
            assert 'dig' in result['hint'] or '8.8.8.8' in result['hint']
            assert result['details']  # exception text included

    @pytest.mark.asyncio
    async def test_test_all_connections(self):
        service = SMTPService()
        service.load_from_config([{'name': 's1', 'host': 'h1'}, {'name': 's2', 'host': 'h2'}])
        
        service.test_connection = AsyncMock()
        service.test_connection.side_effect = [{'success': True}, {'success': False}]
        
        results = await service.test_all_connections()
        
        assert len(results) == 2
        assert results[0]['success'] is True
        assert results[1]['success'] is False

    def test_get_server_status(self):
        service = SMTPService()
        service.load_from_config([{'name': 's1', 'host': 'h1'}])
        service.get_connection_pool()
        
        # Mock circuit breaker inside config
        config = service._configs[0]
        config.runtime.circuit_breaker = MagicMock()
        config.runtime.circuit_breaker.get_stats.return_value = {'state': 'closed'}
        
        status = service.get_server_status()
        
        assert len(status) == 1
        assert status[0]['name'] == 's1'
        assert status[0]['circuit_state'] == 'closed'


class TestAsyncIOExtended:
    
    @pytest.mark.asyncio
    async def test_async_write_read_cycle(self, tmp_path):
        f = tmp_path / "test.txt"
        path = str(f)
        
        await async_write_file(path, "content")
        assert f.read_text(encoding='utf-8') == "content"
        
        content = await async_read_file(path)
        assert content == "content"

    @pytest.mark.asyncio
    async def test_async_write_line_creates_dir(self, tmp_path):
        d = tmp_path / "subdir"
        f = d / "test.txt"
        path = str(f)
        
        await async_write_line(path, "line")
        
        assert d.exists()
        assert f.read_text(encoding='utf-8') == "line\n"

    @pytest.mark.asyncio
    async def test_async_iter_lines(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\n", encoding='utf-8')
        path = str(f)
        
        lines = []
        async for line in async_iter_lines(path):
            lines.append(line)
        
        assert lines == ["line1", "line2"]

    @pytest.mark.asyncio
    async def test_file_logger_buffering(self, tmp_path):
        f = tmp_path / "log.txt"
        path = str(f)
        
        logger = AsyncFileLogger(path, buffer_size=3)
        await logger.start()
        
        # No write yet
        await logger.log("msg1")
        assert not f.exists()
        
        await logger.log("msg2")
        await logger.log("msg3") # Should flush (size 3)
        
        # Give a small delay for IO
        await asyncio.sleep(0.1)
        
        assert f.exists()
        content = f.read_text(encoding='utf-8')
        assert "msg1" in content
        assert "msg3" in content
        
        await logger.stop()

    @pytest.mark.asyncio
    async def test_file_logger_flush_interval(self, tmp_path):
        f = tmp_path / "log.txt"
        path = str(f)
        
        # Very short interval
        logger = AsyncFileLogger(path, buffer_size=100, flush_interval=0.1)
        await logger.start()
        
        await logger.log("msg1")
        assert not f.exists()
        
        # Wait for flush loop
        await asyncio.sleep(0.25)
        
        assert f.exists()
        assert "msg1" in f.read_text(encoding='utf-8')
        
        await logger.stop()

    @pytest.mark.asyncio
    async def test_file_logger_convenience_methods(self, tmp_path):
        f = tmp_path / "log.txt"
        path = str(f)
        
        logger = AsyncFileLogger(path, buffer_size=1)
        await logger.start()
        
        await logger.log_success("test@email.com", "sent")
        await asyncio.sleep(0.1) # Wait for flush
        
        content = f.read_text(encoding='utf-8')
        assert "SUCCESS" in content
        assert "test@email.com" in content
        
        await logger.log_failure("fail@email.com", "error")
        await asyncio.sleep(0.1)
        
        content = f.read_text(encoding='utf-8')
        assert "FAILURE" in content
        
        await logger.stop()
