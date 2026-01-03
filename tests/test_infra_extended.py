
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
import aiofiles

from mercury.services.smtp_service import SMTPService
from mercury.utils.async_io import (
    async_write_line, async_write_file, async_read_file, 
    async_read_lines, async_iter_lines, async_file_exists, 
    async_append_json_line, AsyncFileLogger
)
from mercury.engine.connection_pool import SMTPServerConfig, SMTPConnectionPool

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
    async def test_test_connection_success(self):
        service = SMTPService()
        service.load_from_config([{'name': 's1', 'host': 'h1'}])
        
        with patch('mercury.engine.connection_pool.AsyncSMTPConnection') as MockConn:
            conn_instance = AsyncMock()
            MockConn.return_value = conn_instance
            
            result = await service.test_connection('s1')
            
            assert result['success'] is True
            conn_instance.connect.assert_awaited_once()
            conn_instance.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        service = SMTPService()
        service.load_from_config([{'name': 's1', 'host': 'h1'}])
        
        with patch('mercury.engine.connection_pool.AsyncSMTPConnection') as MockConn:
            conn_instance = AsyncMock()
            conn_instance.connect.side_effect = Exception("Connection failed")
            MockConn.return_value = conn_instance
            
            result = await service.test_connection('s1')
            
            assert result['success'] is False
            assert "Connection failed" in result['error']

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
        config.circuit_breaker = MagicMock()
        config.circuit_breaker.get_stats.return_value = {'state': 'closed'}
        
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
