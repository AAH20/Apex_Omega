"""APEX-OS distributed tracing, request correlation, and performance profiling.

Provides OpenTelemetry-inspired distributed tracing with spans and trace context,
request correlation for tracking requests across services, and lightweight
performance profiling with timers and snapshots.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterator


# ── Span Kind ─────────────────────────────────────────────────────────


class SpanKind(Enum):
    """The kind of a span."""

    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


# ── Span ──────────────────────────────────────────────────────────────


class Span:
    """A single operation within a trace."""

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        operation: str,
        parent_span_id: str | None = None,
        service_name: str = "unknown",
        kind: SpanKind = SpanKind.INTERNAL,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.operation = operation
        self.parent_span_id = parent_span_id
        self.service_name = service_name
        self.kind = kind
        self.tags: dict[str, Any] = {}
        self.logs: list[dict[str, Any]] = []
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.is_error: bool = False

    def start(self) -> None:
        """Start the span timer."""
        self.start_time = time.monotonic()

    def end(self) -> None:
        """End the span timer."""
        self.end_time = time.monotonic()

    @property
    def duration_ms(self) -> float | None:
        """Get the duration in milliseconds, or None if not ended."""
        if self.start_time is None or self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000.0

    def set_tag(self, key: str, value: Any) -> None:
        """Set a tag on the span."""
        self.tags[key] = value

    def set_error(self, is_error: bool = True) -> None:
        """Mark the span as an error."""
        self.is_error = is_error

    def log(self, event: str, **fields: Any) -> None:
        """Add a log entry to the span."""
        self.logs.append(
            {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "event": event,
                "fields": fields,
            }
        )

    def context(self) -> SpanContext:
        """Get the span context for propagation."""
        return SpanContext(trace_id=self.trace_id, span_id=self.span_id)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "service_name": self.service_name,
            "kind": self.kind.value,
            "tags": self.tags,
            "logs": self.logs,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "error": self.is_error,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


# ── Span Context ──────────────────────────────────────────────────────


class SpanContext:
    """Context for propagating trace information across service boundaries."""

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None = None,
        baggage: dict[str, str] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.baggage = baggage or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "baggage": self.baggage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpanContext:
        """Create from dictionary."""
        return cls(
            trace_id=data["trace_id"],
            span_id=data["span_id"],
            parent_span_id=data.get("parent_span_id"),
            baggage=data.get("baggage", {}),
        )


# ── Context Propagation ───────────────────────────────────────────────


def inject_context(context: SpanContext, carrier: dict[str, str]) -> None:
    """Inject span context into a carrier (e.g., HTTP headers)."""
    carrier["x-trace-id"] = context.trace_id
    carrier["x-span-id"] = context.span_id
    if context.parent_span_id:
        carrier["x-parent-span-id"] = context.parent_span_id
    if context.baggage:
        carrier["x-baggage"] = json.dumps(context.baggage)


def extract_context(carrier: dict[str, str]) -> SpanContext | None:
    """Extract span context from a carrier (e.g., HTTP headers)."""
    trace_id = carrier.get("x-trace-id")
    span_id = carrier.get("x-span-id")
    if not trace_id or not span_id:
        return None
    parent_span_id = carrier.get("x-parent-span-id")
    baggage: dict[str, str] = {}
    baggage_raw = carrier.get("x-baggage")
    if baggage_raw:
        try:
            baggage = json.loads(baggage_raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        baggage=baggage,
    )


# ── Tracer ────────────────────────────────────────────────────────────


class Tracer:
    """Creates and manages spans for distributed tracing."""

    def __init__(self, service_name: str = "unknown") -> None:
        self.service_name = service_name
        self.spans: list[Span] = []
        self._current_span: Span | None = None
        self._lock = threading.Lock()

    def start_span(
        self,
        operation: str,
        parent_context: SpanContext | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
    ) -> Span:
        """Start a new span."""
        if parent_context:
            trace_id = parent_context.trace_id
            parent_span_id = parent_context.span_id
        else:
            trace_id = str(uuid.uuid4())
            parent_span_id = None

        span = Span(
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
            operation=operation,
            parent_span_id=parent_span_id,
            service_name=self.service_name,
            kind=kind,
        )
        span.start()
        return span

    def set_current_span(self, span: Span) -> None:
        """Set the current active span."""
        with self._lock:
            self._current_span = span

    def get_current_span(self) -> Span | None:
        """Get the current active span."""
        with self._lock:
            return self._current_span

    def clear_current_span(self) -> None:
        """Clear the current active span."""
        with self._lock:
            self._current_span = None

    def record_span(self, span: Span) -> None:
        """Record a finished span."""
        with self._lock:
            self.spans.append(span)


# ── Trace ─────────────────────────────────────────────────────────────


class Trace:
    """A collection of spans forming a complete trace."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.spans: list[Span] = []

    def add_span(self, span: Span) -> None:
        """Add a span to the trace."""
        self.spans.append(span)

    def get_root_span(self) -> Span | None:
        """Get the root span (the one with no parent)."""
        for span in self.spans:
            if span.parent_span_id is None:
                return span
        return None

    @property
    def duration_ms(self) -> float | None:
        """Get the total trace duration in milliseconds."""
        if not self.spans:
            return None
        start_times = [s.start_time for s in self.spans if s.start_time is not None]
        end_times = [s.end_time for s in self.spans if s.end_time is not None]
        if not start_times or not end_times:
            return None
        return (max(end_times) - min(start_times)) * 1000.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "spans": [s.to_dict() for s in self.spans],
            "duration_ms": self.duration_ms,
        }


# ── Correlation ID Generator ──────────────────────────────────────────


class CorrelationIdGenerator:
    """Generates unique correlation IDs."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix

    def generate(self) -> str:
        """Generate a new correlation ID."""
        cid = str(uuid.uuid4())
        if self.prefix:
            return f"{self.prefix}-{cid}"
        return cid


# ── Correlation Context ───────────────────────────────────────────────


class CorrelationContext:
    """Thread-local correlation context."""

    def __init__(self) -> None:
        self._correlation_id: str | None = None
        self._lock = threading.Lock()

    def set(self, correlation_id: str) -> None:
        """Set the correlation ID."""
        with self._lock:
            self._correlation_id = correlation_id

    def get(self) -> str | None:
        """Get the current correlation ID."""
        with self._lock:
            return self._correlation_id

    def clear(self) -> None:
        """Clear the correlation ID."""
        with self._lock:
            self._correlation_id = None

    def is_set(self) -> bool:
        """Check if a correlation ID is set."""
        with self._lock:
            return self._correlation_id is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {"correlation_id": self._correlation_id}


# ── Request Correlator ────────────────────────────────────────────────


class RequestCorrelator:
    """Correlates requests across services using correlation IDs."""

    def __init__(self) -> None:
        self._correlations: dict[str, str] = {}
        self._generator = CorrelationIdGenerator()
        self._lock = threading.Lock()

    def correlate(self, request_id: str, correlation_id: str | None = None) -> str:
        """Correlate a request with a correlation ID."""
        with self._lock:
            if correlation_id is None:
                correlation_id = self._generator.generate()
            self._correlations[request_id] = correlation_id
            return correlation_id

    def get(self, request_id: str) -> str | None:
        """Get the correlation ID for a request."""
        with self._lock:
            return self._correlations.get(request_id)

    def remove(self, request_id: str) -> None:
        """Remove a correlation."""
        with self._lock:
            self._correlations.pop(request_id, None)

    def clear(self) -> None:
        """Clear all correlations."""
        with self._lock:
            self._correlations.clear()


# ── Performance Timer ─────────────────────────────────────────────────


class PerformanceTimer:
    """A simple performance timer."""

    def __init__(self) -> None:
        self.start_time: float | None = None
        self.end_time: float | None = None

    def start(self) -> None:
        """Start the timer."""
        self.start_time = time.monotonic()

    def stop(self) -> float:
        """Stop the timer and return elapsed milliseconds."""
        if self.start_time is None:
            raise RuntimeError("Timer was not started")
        self.end_time = time.monotonic()
        return (self.end_time - self.start_time) * 1000.0

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds without stopping."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.monotonic()
        return (end - self.start_time) * 1000.0

    def reset(self) -> None:
        """Reset the timer."""
        self.start_time = None
        self.end_time = None


# ── Profiler ──────────────────────────────────────────────────────────


class Profiler:
    """A context manager for profiling code blocks."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.timer = PerformanceTimer()
        self.is_active = False
        self.duration_ms: float | None = None

    def __enter__(self) -> Profiler:
        self.timer.start()
        self.is_active = True
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.duration_ms = self.timer.stop()
        self.is_active = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "operation": self.operation,
            "duration_ms": self.duration_ms,
            "is_active": self.is_active,
        }


# ── Performance Profiler ──────────────────────────────────────────────


class PerformanceProfiler:
    """Profiles performance of code blocks and stores results."""

    def __init__(self) -> None:
        self.results: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def profile(self, name: str, fn: Callable[[], Any]) -> Any:
        """Profile a function call and store the result."""
        timer = PerformanceTimer()
        timer.start()
        result = fn()
        elapsed = timer.stop()
        with self._lock:
            self.results[name].append(elapsed)
        return result

    @contextmanager
    def profile_block(self, name: str) -> Iterator[None]:
        """Context manager for profiling a block of code."""
        timer = PerformanceTimer()
        timer.start()
        yield
        elapsed = timer.stop()
        with self._lock:
            self.results[name].append(elapsed)

    def get_average(self, name: str) -> float:
        """Get the average duration for a named operation."""
        with self._lock:
            values = self.results.get(name, [])
            if not values:
                return 0.0
            return statistics.mean(values)

    def get_stats(self, name: str) -> dict[str, float]:
        """Get statistics for a named operation."""
        with self._lock:
            values = self.results.get(name, [])
            if not values:
                return {"count": 0, "avg": 0.0, "min": 0.0, "max": 0.0, "total": 0.0}
            return {
                "count": len(values),
                "avg": statistics.mean(values),
                "min": min(values),
                "max": max(values),
                "total": sum(values),
            }

    def clear(self) -> None:
        """Clear all results."""
        with self._lock:
            self.results.clear()


# ── Performance Snapshot ──────────────────────────────────────────────


class PerformanceSnapshot:
    """A point-in-time snapshot of performance metrics."""

    def __init__(self) -> None:
        self.timestamp = datetime.now(tz=timezone.utc).isoformat()
        self.metrics: dict[str, float] = {}

    def add_metric(self, name: str, value: float) -> None:
        """Add a metric to the snapshot."""
        self.metrics[name] = value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "metrics": self.metrics,
        }


# ── Performance Report ────────────────────────────────────────────────


class PerformanceReport:
    """A report aggregating multiple performance snapshots."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.snapshots: list[PerformanceSnapshot] = []

    def add_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        """Add a snapshot to the report."""
        self.snapshots.append(snapshot)

    def get_summary(self) -> dict[str, dict[str, float]]:
        """Get a summary of all metrics across snapshots."""
        all_metrics: dict[str, list[float]] = defaultdict(list)
        for snapshot in self.snapshots:
            for name, value in snapshot.metrics.items():
                all_metrics[name].append(value)

        summary: dict[str, dict[str, float]] = {}
        for name, values in all_metrics.items():
            summary[name] = {
                "count": len(values),
                "avg": statistics.mean(values),
                "min": min(values),
                "max": max(values),
            }
        return summary

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "summary": self.get_summary(),
        }
