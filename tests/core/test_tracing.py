"""Unit tests for APEX-OS distributed tracing, request correlation, and performance profiling."""
import json
import time
import uuid
from datetime import datetime, timezone

import pytest

from src.core.tracing import (
    CorrelationContext,
    CorrelationIdGenerator,
    PerformanceProfiler,
    PerformanceReport,
    PerformanceSnapshot,
    PerformanceTimer,
    Profiler,
    RequestCorrelator,
    Span,
    SpanContext,
    SpanKind,
    Trace,
    Tracer,
    inject_context,
    extract_context,
)


# ---------------------------------------------------------------------------
# Span tests
# ---------------------------------------------------------------------------


class TestSpan:
    def test_span_creation_with_trace_and_span_id(self):
        span = Span(trace_id="trace-1", span_id="span-1", operation="test-op")
        assert span.trace_id == "trace-1"
        assert span.span_id == "span-1"
        assert span.operation == "test-op"
        assert span.parent_span_id is None

    def test_span_with_parent(self):
        span = Span(trace_id="t1", span_id="s2", operation="child", parent_span_id="s1")
        assert span.parent_span_id == "s1"

    def test_span_start_end_timing(self):
        span = Span(trace_id="t1", span_id="s1", operation="timed")
        span.start()
        time.sleep(0.01)
        span.end()
        assert span.start_time is not None
        assert span.end_time is not None
        assert span.duration_ms is not None
        assert span.duration_ms >= 10.0

    def test_span_not_ended_has_no_duration(self):
        span = Span(trace_id="t1", span_id="s1", operation="incomplete")
        span.start()
        assert span.duration_ms is None

    def test_span_add_tag(self):
        span = Span(trace_id="t1", span_id="s1", operation="tagged")
        span.set_tag("http.method", "GET")
        span.set_tag("http.status_code", 200)
        assert span.tags["http.method"] == "GET"
        assert span.tags["http.status_code"] == 200

    def test_span_add_log(self):
        span = Span(trace_id="t1", span_id="s1", operation="logged")
        span.log("event", key="value")
        assert len(span.logs) == 1
        assert span.logs[0]["event"] == "event"
        assert span.logs[0]["fields"]["key"] == "value"

    def test_span_to_dict(self):
        span = Span(trace_id="t1", span_id="s1", operation="serializable", parent_span_id="root")
        span.set_tag("env", "test")
        span.start()
        span.end()
        d = span.to_dict()
        assert d["trace_id"] == "t1"
        assert d["span_id"] == "s1"
        assert d["parent_span_id"] == "root"
        assert d["operation"] == "serializable"
        assert d["tags"]["env"] == "test"
        assert "start_time" in d
        assert "end_time" in d
        assert "duration_ms" in d

    def test_span_to_json(self):
        span = Span(trace_id="t1", span_id="s1", operation="json-test")
        span.start()
        span.end()
        json_str = span.to_json()
        parsed = json.loads(json_str)
        assert parsed["trace_id"] == "t1"
        assert parsed["operation"] == "json-test"

    def test_span_kind(self):
        span = Span(trace_id="t1", span_id="s1", operation="server-op", kind=SpanKind.SERVER)
        assert span.kind == SpanKind.SERVER
        d = span.to_dict()
        assert d["kind"] == "SERVER"

    def test_span_error_flag(self):
        span = Span(trace_id="t1", span_id="s1", operation="error-op")
        span.set_error(True)
        assert span.is_error is True
        d = span.to_dict()
        assert d["error"] is True


# ---------------------------------------------------------------------------
# SpanContext tests
# ---------------------------------------------------------------------------


class TestSpanContext:
    def test_span_context_creation(self):
        ctx = SpanContext(trace_id="t1", span_id="s1")
        assert ctx.trace_id == "t1"
        assert ctx.span_id == "s1"
        assert ctx.parent_span_id is None

    def test_span_context_with_parent(self):
        ctx = SpanContext(trace_id="t1", span_id="s2", parent_span_id="s1")
        assert ctx.parent_span_id == "s1"

    def test_span_context_baggage(self):
        ctx = SpanContext(trace_id="t1", span_id="s1", baggage={"user": "alice"})
        assert ctx.baggage["user"] == "alice"

    def test_span_context_to_dict(self):
        ctx = SpanContext(trace_id="t1", span_id="s1", baggage={"k": "v"})
        d = ctx.to_dict()
        assert d["trace_id"] == "t1"
        assert d["span_id"] == "s1"
        assert d["baggage"] == {"k": "v"}

    def test_span_context_from_dict(self):
        data = {"trace_id": "t1", "span_id": "s1", "parent_span_id": "root", "baggage": {"a": "b"}}
        ctx = SpanContext.from_dict(data)
        assert ctx.trace_id == "t1"
        assert ctx.span_id == "s1"
        assert ctx.parent_span_id == "root"
        assert ctx.baggage == {"a": "b"}


# ---------------------------------------------------------------------------
# Tracer tests
# ---------------------------------------------------------------------------


class TestTracer:
    def test_tracer_creates_span(self):
        tracer = Tracer("test-service")
        span = tracer.start_span("operation")
        assert span.trace_id is not None
        assert span.span_id is not None
        assert span.operation == "operation"
        assert span.service_name == "test-service"

    def test_tracer_span_ids_are_unique(self):
        tracer = Tracer("test-service")
        s1 = tracer.start_span("op1")
        s2 = tracer.start_span("op2")
        assert s1.span_id != s2.span_id

    def test_tracer_child_span_inherits_trace_id(self):
        tracer = Tracer("test-service")
        parent = tracer.start_span("parent")
        child = tracer.start_span("child", parent_context=parent.context())
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.span_id

    def test_tracer_current_span(self):
        tracer = Tracer("test-service")
        span = tracer.start_span("current")
        tracer.set_current_span(span)
        assert tracer.get_current_span() is span

    def test_tracer_clear_current_span(self):
        tracer = Tracer("test-service")
        span = tracer.start_span("temp")
        tracer.set_current_span(span)
        tracer.clear_current_span()
        assert tracer.get_current_span() is None

    def test_tracer_generates_trace_ids(self):
        tracer = Tracer("test-service")
        span = tracer.start_span("op")
        # Should be a valid UUID
        uuid.UUID(span.trace_id)

    def test_tracer_records_finished_spans(self):
        tracer = Tracer("test-service")
        span = tracer.start_span("recorded")
        span.end()
        tracer.record_span(span)
        assert span in tracer.spans

    def test_tracer_start_span_with_context(self):
        tracer = Tracer("test-service")
        ctx = SpanContext(trace_id="existing-trace", span_id="existing-span")
        span = tracer.start_span("with-context", parent_context=ctx)
        assert span.trace_id == "existing-trace"
        assert span.parent_span_id == "existing-span"


# ---------------------------------------------------------------------------
# Trace tests
# ---------------------------------------------------------------------------


class TestTrace:
    def test_trace_creation(self):
        trace = Trace("trace-1")
        assert trace.trace_id == "trace-1"
        assert len(trace.spans) == 0

    def test_trace_add_span(self):
        trace = Trace("trace-1")
        span = Span(trace_id="trace-1", span_id="s1", operation="op")
        trace.add_span(span)
        assert len(trace.spans) == 1
        assert trace.spans[0] is span

    def test_trace_root_span(self):
        trace = Trace("trace-1")
        root = Span(trace_id="trace-1", span_id="root", operation="root-op")
        child = Span(trace_id="trace-1", span_id="child", operation="child-op", parent_span_id="root")
        trace.add_span(root)
        trace.add_span(child)
        assert trace.get_root_span() is root

    def test_trace_duration(self):
        trace = Trace("trace-1")
        span = Span(trace_id="trace-1", span_id="s1", operation="op")
        span.start()
        time.sleep(0.01)
        span.end()
        trace.add_span(span)
        assert trace.duration_ms is not None
        assert trace.duration_ms >= 10.0

    def test_trace_to_dict(self):
        trace = Trace("trace-1")
        span = Span(trace_id="trace-1", span_id="s1", operation="op")
        span.start()
        span.end()
        trace.add_span(span)
        d = trace.to_dict()
        assert d["trace_id"] == "trace-1"
        assert len(d["spans"]) == 1


# ---------------------------------------------------------------------------
# Context propagation tests
# ---------------------------------------------------------------------------


class TestContextPropagation:
    def test_inject_context(self):
        ctx = SpanContext(trace_id="t1", span_id="s1", baggage={"key": "val"})
        carrier = {}
        inject_context(ctx, carrier)
        assert carrier["x-trace-id"] == "t1"
        assert carrier["x-span-id"] == "s1"
        assert "x-baggage" in carrier

    def test_extract_context(self):
        carrier = {"x-trace-id": "t1", "x-span-id": "s1", "x-baggage": json.dumps({"k": "v"})}
        ctx = extract_context(carrier)
        assert ctx is not None
        assert ctx.trace_id == "t1"
        assert ctx.span_id == "s1"
        assert ctx.baggage == {"k": "v"}

    def test_extract_context_empty_carrier(self):
        ctx = extract_context({})
        assert ctx is None

    def test_inject_extract_roundtrip(self):
        original = SpanContext(trace_id="t1", span_id="s1", baggage={"user": "bob"})
        carrier = {}
        inject_context(original, carrier)
        extracted = extract_context(carrier)
        assert extracted.trace_id == original.trace_id
        assert extracted.span_id == original.span_id
        assert extracted.baggage == original.baggage


# ---------------------------------------------------------------------------
# Correlation ID tests
# ---------------------------------------------------------------------------


class TestCorrelationIdGenerator:
    def test_generates_unique_ids(self):
        gen = CorrelationIdGenerator()
        ids = [gen.generate() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_generates_valid_uuid(self):
        gen = CorrelationIdGenerator()
        cid = gen.generate()
        uuid.UUID(cid)

    def test_generates_with_prefix(self):
        gen = CorrelationIdGenerator(prefix="req")
        cid = gen.generate()
        assert cid.startswith("req-")


class TestCorrelationContext:
    def test_set_and_get(self):
        ctx = CorrelationContext()
        ctx.set("corr-123")
        assert ctx.get() == "corr-123"

    def test_clear(self):
        ctx = CorrelationContext()
        ctx.set("corr-123")
        ctx.clear()
        assert ctx.get() is None

    def test_is_set(self):
        ctx = CorrelationContext()
        assert not ctx.is_set()
        ctx.set("corr-123")
        assert ctx.is_set()

    def test_to_dict(self):
        ctx = CorrelationContext()
        ctx.set("corr-123")
        d = ctx.to_dict()
        assert d["correlation_id"] == "corr-123"


class TestRequestCorrelator:
    def test_correlate_request(self):
        corr = RequestCorrelator()
        cid = corr.correlate("request-1")
        assert cid is not None
        assert corr.get("request-1") == cid

    def test_correlate_generates_unique_ids(self):
        corr = RequestCorrelator()
        c1 = corr.correlate("req-1")
        c2 = corr.correlate("req-2")
        assert c1 != c2

    def test_correlate_with_existing_id(self):
        corr = RequestCorrelator()
        cid = corr.correlate("req-1", correlation_id="existing-corr")
        assert cid == "existing-corr"

    def test_remove_correlation(self):
        corr = RequestCorrelator()
        corr.correlate("req-1")
        corr.remove("req-1")
        assert corr.get("req-1") is None

    def test_clear_all(self):
        corr = RequestCorrelator()
        corr.correlate("req-1")
        corr.correlate("req-2")
        corr.clear()
        assert corr.get("req-1") is None
        assert corr.get("req-2") is None


# ---------------------------------------------------------------------------
# Performance profiling tests
# ---------------------------------------------------------------------------


class TestPerformanceTimer:
    def test_timer_measures_duration(self):
        timer = PerformanceTimer()
        timer.start()
        time.sleep(0.01)
        elapsed = timer.stop()
        assert elapsed >= 10.0

    def test_timer_elapsed_property(self):
        timer = PerformanceTimer()
        timer.start()
        time.sleep(0.005)
        elapsed = timer.elapsed_ms
        assert elapsed >= 5.0
        timer.stop()

    def test_timer_not_started_raises(self):
        timer = PerformanceTimer()
        with pytest.raises(RuntimeError):
            timer.stop()

    def test_timer_reset(self):
        timer = PerformanceTimer()
        timer.start()
        time.sleep(0.005)
        timer.stop()
        timer.reset()
        assert timer.start_time is None
        assert timer.end_time is None


class TestProfiler:
    def test_profiler_context_manager(self):
        profiler = Profiler("test-op")
        with profiler:
            time.sleep(0.01)
        assert profiler.duration_ms is not None
        assert profiler.duration_ms >= 10.0

    def test_profiler_records_operation_name(self):
        profiler = Profiler("my-operation")
        with profiler:
            pass
        assert profiler.operation == "my-operation"

    def test_profiler_is_active_inside_context(self):
        profiler = Profiler("active-test")
        with profiler:
            assert profiler.is_active
        assert not profiler.is_active

    def test_profiler_to_dict(self):
        profiler = Profiler("dict-test")
        with profiler:
            time.sleep(0.005)
        d = profiler.to_dict()
        assert d["operation"] == "dict-test"
        assert d["duration_ms"] >= 5.0


class TestPerformanceProfiler:
    def test_profile_block(self):
        prof = PerformanceProfiler()
        prof.profile("block-1", lambda: time.sleep(0.01))
        assert len(prof.results["block-1"]) == 1
        assert prof.results["block-1"][0] >= 10.0

    def test_profile_stores_results(self):
        prof = PerformanceProfiler()
        prof.profile("block-1", lambda: time.sleep(0.005))
        assert "block-1" in prof.results
        assert len(prof.results["block-1"]) == 1
        assert prof.results["block-1"][0] >= 5.0

    def test_profile_multiple_calls(self):
        prof = PerformanceProfiler()
        prof.profile("multi", lambda: time.sleep(0.005))
        prof.profile("multi", lambda: time.sleep(0.005))
        assert len(prof.results["multi"]) == 2

    def test_get_average(self):
        prof = PerformanceProfiler()
        prof.profile("avg", lambda: time.sleep(0.005))
        prof.profile("avg", lambda: time.sleep(0.005))
        avg = prof.get_average("avg")
        assert avg >= 5.0

    def test_get_average_no_data(self):
        prof = PerformanceProfiler()
        assert prof.get_average("nonexistent") == 0.0

    def test_clear(self):
        prof = PerformanceProfiler()
        prof.profile("clear-me", lambda: time.sleep(0.005))
        prof.clear()
        assert len(prof.results) == 0


class TestPerformanceSnapshot:
    def test_snapshot_creation(self):
        snap = PerformanceSnapshot()
        assert snap.timestamp is not None
        assert snap.metrics is not None

    def test_snapshot_add_metric(self):
        snap = PerformanceSnapshot()
        snap.add_metric("cpu_percent", 45.5)
        assert snap.metrics["cpu_percent"] == 45.5

    def test_snapshot_to_dict(self):
        snap = PerformanceSnapshot()
        snap.add_metric("memory_mb", 1024.0)
        d = snap.to_dict()
        assert d["metrics"]["memory_mb"] == 1024.0
        assert "timestamp" in d


class TestPerformanceReport:
    def test_report_creation(self):
        report = PerformanceReport("test-report")
        assert report.name == "test-report"
        assert len(report.snapshots) == 0

    def test_report_add_snapshot(self):
        report = PerformanceReport("test-report")
        snap = PerformanceSnapshot()
        snap.add_metric("latency_ms", 50.0)
        report.add_snapshot(snap)
        assert len(report.snapshots) == 1

    def test_report_summary(self):
        report = PerformanceReport("test-report")
        snap1 = PerformanceSnapshot()
        snap1.add_metric("latency_ms", 30.0)
        snap2 = PerformanceSnapshot()
        snap2.add_metric("latency_ms", 50.0)
        report.add_snapshot(snap1)
        report.add_snapshot(snap2)
        summary = report.get_summary()
        assert summary["latency_ms"]["count"] == 2
        assert summary["latency_ms"]["avg"] == 40.0
        assert summary["latency_ms"]["min"] == 30.0
        assert summary["latency_ms"]["max"] == 50.0

    def test_report_to_dict(self):
        report = PerformanceReport("test-report")
        snap = PerformanceSnapshot()
        snap.add_metric("requests", 100.0)
        report.add_snapshot(snap)
        d = report.to_dict()
        assert d["name"] == "test-report"
        assert len(d["snapshots"]) == 1
        assert "summary" in d
