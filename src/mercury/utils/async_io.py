"""Async file I/O utilities using aiofiles."""

import os
import asyncio
import logging
from typing import Optional, List, AsyncIterator
from datetime import datetime, UTC

import aiofiles
import aiofiles.os

logger = logging.getLogger(__name__)


async def async_write_line(filepath: str, content: str, mode: str = 'a') -> None:
    """
    Write a line to a file asynchronously.
    
    Args:
        filepath: Path to file
        content: Content to write (newline added automatically)
        mode: File mode ('a' for append, 'w' for overwrite)
    """
    # Ensure directory exists
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    
    async with aiofiles.open(filepath, mode=mode, encoding='utf-8') as f:
        await f.write(content + '\n')


async def async_write_file(filepath: str, content: str) -> None:
    """
    Write content to a file asynchronously.
    
    Args:
        filepath: Path to file
        content: Content to write
    """
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    
    async with aiofiles.open(filepath, mode='w', encoding='utf-8') as f:
        await f.write(content)


async def async_read_file(filepath: str) -> str:
    """
    Read file content asynchronously.
    
    Args:
        filepath: Path to file
        
    Returns:
        File content as string
    """
    async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
        return await f.read()


async def async_read_lines(filepath: str) -> List[str]:
    """
    Read file lines asynchronously.
    
    Args:
        filepath: Path to file
        
    Returns:
        List of lines
    """
    async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
        content = await f.read()
        return content.splitlines()


async def async_iter_lines(filepath: str) -> AsyncIterator[str]:
    """
    Iterate over file lines asynchronously.
    
    Args:
        filepath: Path to file
        
    Yields:
        Lines from file
    """
    async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
        async for line in f:
            yield line.rstrip('\n\r')


async def async_file_exists(filepath: str) -> bool:
    """Check if file exists asynchronously."""
    try:
        await aiofiles.os.stat(filepath)
        return True
    except FileNotFoundError:
        return False


async def async_append_json_line(filepath: str, data: dict) -> None:
    """
    Append a JSON line to file (JSONL format).
    
    Args:
        filepath: Path to file
        data: Dictionary to write as JSON
    """
    import json
    line = json.dumps(data, default=str)
    await async_write_line(filepath, line)


class AsyncFileLogger:
    """
    Async file logger for high-performance logging during bulk operations.
    
    Buffers writes and flushes periodically or when buffer is full.
    """
    
    def __init__(
        self,
        filepath: str,
        buffer_size: int = 100,
        flush_interval: float = 5.0
    ):
        """
        Initialize async file logger.
        
        Args:
            filepath: Path to log file
            buffer_size: Number of lines to buffer before flushing
            flush_interval: Maximum seconds between flushes
        """
        self.filepath = filepath
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        
        self._buffer: List[str] = []
        self._lock = asyncio.Lock()
        self._last_flush = datetime.now(UTC)
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the background flush task."""
        if self._running:
            return
        
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        
        # Ensure directory exists
        directory = os.path.dirname(self.filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
    
    async def stop(self) -> None:
        """Stop and flush remaining buffer."""
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        await self.flush()
    
    async def log(self, message: str) -> None:
        """
        Log a message (buffered).
        
        Args:
            message: Message to log
        """
        async with self._lock:
            self._buffer.append(message)
            
            if len(self._buffer) >= self.buffer_size:
                await self._flush_buffer()
    
    async def log_success(self, email: str, details: str = "") -> None:
        """Log successful send."""
        timestamp = datetime.now(UTC).isoformat()
        line = f"{timestamp}|SUCCESS|{email}"
        if details:
            line += f"|{details}"
        await self.log(line)
    
    async def log_failure(self, email: str, error: str) -> None:
        """Log failed send."""
        timestamp = datetime.now(UTC).isoformat()
        await self.log(f"{timestamp}|FAILURE|{email}|{error}")
    
    async def flush(self) -> None:
        """Force flush buffer to disk."""
        async with self._lock:
            await self._flush_buffer()
    
    async def _flush_buffer(self) -> None:
        """Internal flush method (must hold lock)."""
        if not self._buffer:
            return
        
        try:
            async with aiofiles.open(self.filepath, mode='a', encoding='utf-8') as f:
                content = '\n'.join(self._buffer) + '\n'
                await f.write(content)
            
            self._buffer.clear()
            self._last_flush = datetime.now(UTC)
            
        except Exception as e:
            logger.error(f"Failed to flush log buffer: {e}")
    
    async def _flush_loop(self) -> None:
        """Background task to periodically flush buffer."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
    
    async def __aenter__(self) -> 'AsyncFileLogger':
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()

