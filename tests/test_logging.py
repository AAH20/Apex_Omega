"""Unit tests for APEX-OS structured logging framework."""

import json
import logging
import time
from pathlib import Path

import pytest

from src.core.logging import (
    AsyncHandler,
    CorrelationIdFilter,
    JSONFormatter,
    LogRecord,
    LogLevel,
    StructuredLogger,
    get_logger,
)


class CaptureHandler(logging.Handler):
    """A handler that captures formatted output for testing."""

    def __init__(self):
        super().__init__()
        self.output: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.output.append(self.format(record))


# ---------------------------------------------------------------------------
# LogRecord tests
# ---------------------------------------------------------------------------


class TestLogRecord:
    def test_log_record_to_dict(self):
        record = LogRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            level="INFO",
            message="test message",
        )
        d = record.to_dict()
        assert d["timestamp"] == "2024-01-01T00:00:00+00:00"
        assert d["level"] == "INFO"
        assert d["message"] == "test message"
        assert "correlation_id" not in d
        assert "extra" not in d

    def test_log_record_with_correlation_id(self):
        record = LogRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            level="INFO",
            message="test",
            correlation_id="abc-123",
        )
        d = record.to_dict()
        assert d["correlation_id"] == "abc-123"

    def test_log_record_with_extra(self):
        record = LogRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            level="INFO",
            message="test",
            extra={"key": "value"},
        )
        d = record.to_dict()
        assert d["extra"] == {"key": "value"}

    def test_log_record_to_json(self):
        record = LogRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            level="INFO",
            message="test",
        )
        json_str = record.to_json()
        parsed = json.loads(json_str)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test"


# ---------------------------------------------------------------------------
# JSONFormatter tests
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    def test_format_basic_record(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test message"
        assert "timestamp" in parsed

    def test_format_with_correlation_id(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "corr-123"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["correlation_id"] == "corr-123"

    def test_format_with_extra(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.extra = {"key": "value"}
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["extra"] == {"key": "value"}


# ---------------------------------------------------------------------------
# CorrelationIdFilter tests
# ---------------------------------------------------------------------------


class TestCorrelationIdFilter:
    def test_set_and_get_correlation_id(self):
        filt = CorrelationIdFilter()
        filt.set_correlation_id("test-corr-123")
        assert filt.get_correlation_id() == "test-corr-123"

    def test_clear_correlation_id(self):
        filt = CorrelationIdFilter()
        filt.set_correlation_id("test-corr-123")
        filt.clear()
        assert filt.get_correlation_id() is None

    def test_filter_injects_correlation_id(self):
        filt = CorrelationIdFilter()
        filt.set_correlation_id("injected-corr")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        result = filt.filter(record)
        assert result is True
        assert record.correlation_id == "injected-corr"

    def test_filter_without_correlation_id(self):
        filt = CorrelationIdFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        result = filt.filter(record)
        assert result is True
        assert record.correlation_id is None


# ---------------------------------------------------------------------------
# AsyncHandler tests
# ---------------------------------------------------------------------------


class TestAsyncHandler:
    def test_async_handler_emits(self):
        capture = CaptureHandler()
        async_handler = AsyncHandler(capture)
        async_handler.start()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="async test",
            args=(),
            exc_info=None,
        )
        async_handler.emit(record)
        time.sleep(0.2)

        assert len(capture.output) == 1
        async_handler.close()

    def test_async_handler_drops_when_full(self):
        class SlowHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.count = 0

            def emit(self, record):
                self.count += 1
                time.sleep(0.01)

        slow_handler = SlowHandler()
        async_handler = AsyncHandler(slow_handler, max_queue_size=2)
        async_handler.start()

        for i in range(10):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=f"msg {i}",
                args=(),
                exc_info=None,
            )
            async_handler.emit(record)

        time.sleep(0.5)
        assert slow_handler.count < 10
        async_handler.close()


# ---------------------------------------------------------------------------
# StructuredLogger tests
# ---------------------------------------------------------------------------


class TestStructuredLogger:
    def test_logger_creates_with_default_correlation_id(self):
        logger = StructuredLogger("test_logger_default_corr")
        assert logger.get_correlation_id() is not None
        assert len(logger.get_correlation_id()) > 0

    def test_logger_set_correlation_id(self):
        logger = StructuredLogger("test_logger_set_corr")
        logger.set_correlation_id("my-corr-id")
        assert logger.get_correlation_id() == "my-corr-id"

    def test_logger_with_custom_correlation_id(self):
        logger = StructuredLogger("test_logger_custom_corr", correlation_id="custom-corr")
        assert logger.get_correlation_id() == "custom-corr"

    def test_logger_level_filtering(self):
        logger = StructuredLogger("test_logger_level", level=LogLevel.WARNING)
        assert logger.level == LogLevel.WARNING

    def test_logger_info_outputs_json(self):
        logger = StructuredLogger("test_logger_info")
        handler = CaptureHandler()
        handler.setFormatter(JSONFormatter())
        logger._logger.addHandler(handler)

        logger.info("test info message", key="value")

        assert len(handler.output) == 1
        parsed = json.loads(handler.output[0])
        assert parsed["message"] == "test info message"
        assert parsed["extra"]["key"] == "value"
        assert parsed["correlation_id"] == logger.get_correlation_id()

    def test_logger_error_outputs_json(self):
        logger = StructuredLogger("test_logger_error")
        handler = CaptureHandler()
        handler.setFormatter(JSONFormatter())
        logger._logger.addHandler(handler)

        logger.error("test error message", error_code=500)

        assert len(handler.output) == 1
        parsed = json.loads(handler.output[0])
        assert parsed["message"] == "test error message"
        assert parsed["extra"]["error_code"] == 500
        assert parsed["level"] == "ERROR"

    def test_logger_debug_filtered_at_warning_level(self):
        logger = StructuredLogger("test_logger_debug_filter", level=LogLevel.WARNING)
        handler = CaptureHandler()
        handler.setFormatter(JSONFormatter())
        logger._logger.addHandler(handler)

        logger.debug("should be filtered")
        logger.info("should also be filtered")
        logger.warning("should pass")

        assert len(handler.output) == 1
        parsed = json.loads(handler.output[0])
        assert parsed["message"] == "should pass"


# ---------------------------------------------------------------------------
# get_logger factory tests
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_get_logger_returns_structured_logger(self):
        logger = get_logger("test_factory")
        assert isinstance(logger, StructuredLogger)

    def test_get_logger_with_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = get_logger("test_factory_file", log_file=log_file)
        logger.info("file test message")
        logger._logger.handlers[0].flush()
        content = log_file.read_text()
        assert "file test message" in content

    def test_get_logger_with_rotation(self, tmp_path):
        log_file = tmp_path / "rotate.log"
        logger = get_logger(
            "test_factory_rotate",
            log_file=log_file,
            max_bytes=100,
            backup_count=2,
        )
        for i in range(20):
            logger.info(f"rotation test message {i}" + "x" * 50)
        logger._logger.handlers[0].flush()
        assert log_file.exists()
        backup_files = list(tmp_path.glob("rotate.log.*"))
        assert len(backup_files) > 0

    def test_get_logger_async(self, tmp_path):
        log_file = tmp_path / "async.log"
        logger = get_logger(
            "test_factory_async",
            log_file=log_file,
            async_logging=True,
        )
        logger.info("async file test")
        time.sleep(0.2)
        for handler in logger._logger.handlers:
            if isinstance(handler, AsyncHandler):
                handler.flush()
        content = log_file.read_text()
        assert "async file test" in content
