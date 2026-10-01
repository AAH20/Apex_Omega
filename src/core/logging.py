"""APEX-OS structured logging framework.

Provides JSON structured logging, log levels, log rotation,
correlation IDs, and async logging.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class LogLevel(Enum):
    """Log levels matching standard logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def to_logging_level(self) -> int:
        """Convert to standard logging module level."""
        return getattr(logging, self.value)


class LogRecord:
    """A structured log record."""

    def __init__(
        self,
        timestamp: str,
        level: str,
        message: str,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.timestamp = timestamp
        self.level = level
        self.message = message
        self.correlation_id = correlation_id
        self.extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
        }
        if self.correlation_id is not None:
            result["correlation_id"] = self.correlation_id
        if self.extra:
            result["extra"] = self.extra
        return result

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON."""
        correlation_id = getattr(record, "correlation_id", None)
        extra = getattr(record, "extra", {})

        log_record = LogRecord(
            timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            level=record.levelname,
            message=record.getMessage(),
            correlation_id=correlation_id,
            extra=extra if extra else None,
        )
        return log_record.to_json()


class CorrelationIdFilter(logging.Filter):
    """Filter that injects correlation IDs into log records."""

    def __init__(self) -> None:
        super().__init__()
        self._correlation_id: str | None = None

    def set_correlation_id(self, correlation_id: str) -> None:
        """Set the correlation ID for subsequent log records."""
        self._correlation_id = correlation_id

    def get_correlation_id(self) -> str | None:
        """Get the current correlation ID."""
        return self._correlation_id

    def clear(self) -> None:
        """Clear the current correlation ID."""
        self._correlation_id = None

    def filter(self, record: logging.LogRecord) -> bool:
        """Inject correlation ID into the log record."""
        record.correlation_id = self._correlation_id
        return True


class AsyncHandler(logging.Handler):
    """Asynchronous logging handler using a background thread."""

    def __init__(
        self,
        handler: logging.Handler,
        max_queue_size: int = 10000,
    ) -> None:
        super().__init__()
        self._handler = handler
        self._queue: queue.Queue[logging.LogRecord | None] = queue.Queue(maxsize=max_queue_size)
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start the background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._process, daemon=True)
        self._thread.start()

    def _process(self) -> None:
        """Process log records from the queue."""
        while self._running:
            try:
                record = self._queue.get(timeout=0.1)
                if record is None:
                    break
                self._handler.emit(record)
            except queue.Empty:
                continue
            except Exception:
                pass

    def emit(self, record: logging.LogRecord) -> None:
        """Queue the log record for async processing."""
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            pass  # Drop log records when queue is full

    def flush(self) -> None:
        """Flush the underlying handler."""
        self._handler.flush()

    def close(self) -> None:
        """Stop the background thread and close."""
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._handler.close()
        super().close()


class StructuredLogger:
    """A structured logger with correlation ID support."""

    def __init__(
        self,
        name: str,
        level: LogLevel = LogLevel.INFO,
        correlation_id: str | None = None,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level.to_logging_level())
        self._correlation_filter = CorrelationIdFilter()
        self._logger.addFilter(self._correlation_filter)
        self._correlation_id = correlation_id or str(uuid.uuid4())
        self._correlation_filter.set_correlation_id(self._correlation_id)

    @property
    def level(self) -> LogLevel:
        """Get the current log level."""
        level_value = self._logger.level
        for lvl in LogLevel:
            if lvl.to_logging_level() == level_value:
                return lvl
        return LogLevel.INFO

    def set_correlation_id(self, correlation_id: str) -> None:
        """Set the correlation ID."""
        self._correlation_id = correlation_id
        self._correlation_filter.set_correlation_id(correlation_id)

    def get_correlation_id(self) -> str:
        """Get the current correlation ID."""
        return self._correlation_id

    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        """Internal log method."""
        extra = kwargs.get("extra", {})
        extra.update({k: v for k, v in kwargs.items() if k != "extra"})
        self._logger.log(level, msg, extra={"extra": extra})

    def debug(self, msg: str, **kwargs: Any) -> None:
        """Log a debug message."""
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        """Log an info message."""
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        """Log a warning message."""
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        """Log an error message."""
        self._log(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        """Log a critical message."""
        self._log(logging.CRITICAL, msg, **kwargs)


def get_logger(
    name: str,
    level: LogLevel = LogLevel.INFO,
    log_file: str | Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    async_logging: bool = False,
    correlation_id: str | None = None,
) -> StructuredLogger:
    """Get a configured structured logger.

    Args:
        name: Logger name.
        level: Log level.
        log_file: Optional file path for file logging.
        max_bytes: Maximum bytes per log file before rotation.
        backup_count: Number of backup files to keep.
        async_logging: Whether to use async logging.
        correlation_id: Optional correlation ID.

    Returns:
        A configured StructuredLogger instance.
    """
    logger = StructuredLogger(name, level=level, correlation_id=correlation_id)

    formatter = JSONFormatter()

    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if async_logging:
            file_handler: logging.Handler = RotatingFileHandler(
                log_path, maxBytes=max_bytes, backupCount=backup_count
            )
            file_handler.setFormatter(formatter)
            async_handler = AsyncHandler(file_handler)
            async_handler.start()
            logger._logger.addHandler(async_handler)
        else:
            file_handler = RotatingFileHandler(
                log_path, maxBytes=max_bytes, backupCount=backup_count
            )
            file_handler.setFormatter(formatter)
            logger._logger.addHandler(file_handler)

    return logger
