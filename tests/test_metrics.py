"""Unit tests for APEX-OS Prometheus metrics collector."""

import threading
import time
import urllib.request

import pytest

from src.core.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    Summary,
    start_http_server,
)


# ── Counter ──────────────────────────────────────────────────────────


def test_counter_inc():
    c = Counter("requests_total", "Total requests")
    c.inc()
    c.inc(5)
    assert c.get() == 6


def test_counter_with_labels():
    c = Counter("requests_total", "Total requests", labelnames=["method"])
    c.labels(method="GET").inc()
    c.labels(method="POST").inc(2)
    assert c.labels(method="GET").get() == 1
    assert c.labels(method="POST").get() == 2


def test_counter_cannot_decrease():
    c = Counter("errors_total", "Total errors")
    c.inc(10)
    with pytest.raises(ValueError):
        c.dec()


# ── Gauge ─────────────────────────────────────────────────────────────


def test_gauge_set_and_delta():
    g = Gauge("temperature_celsius", "Temperature")
    g.set(25.0)
    assert g.get() == 25.0
    g.inc(3.5)
    assert g.get() == 28.5
    g.dec(1.0)
    assert g.get() == 27.5


def test_gauge_with_labels():
    g = Gauge("queue_depth", "Queue depth", labelnames=["queue"])
    g.labels(queue="default").set(10)
    g.labels(queue="priority").set(3)
    assert g.labels(queue="default").get() == 10
    assert g.labels(queue="priority").get() == 3


# ── Histogram ─────────────────────────────────────────────────────────


def test_histogram_observe():
    h = Histogram(
        "request_duration_seconds",
        "Request duration",
        buckets=[0.1, 0.5, 1.0, 5.0],
    )
    h.observe(0.3)
    h.observe(0.7)
    h.observe(2.0)
    assert h.get_count() == 3
    assert h.get_sum() == pytest.approx(3.0)


def test_histogram_bucket_counts():
    h = Histogram(
        "latency_seconds",
        "Latency",
        buckets=[1.0, 5.0, 10.0],
    )
    h.observe(0.5)
    h.observe(3.0)
    h.observe(7.0)
    h.observe(15.0)
    buckets = h.get_buckets()
    assert buckets[1.0] == 1
    assert buckets[5.0] == 2
    assert buckets[10.0] == 3
    assert buckets["+Inf"] == 4


# ── Summary ───────────────────────────────────────────────────────────


def test_summary_observe():
    s = Summary(
        "response_size_bytes",
        "Response size",
        quantiles=[0.5, 0.95, 0.99],
    )
    for i in range(1, 101):
        s.observe(float(i))
    assert s.get_count() == 100
    assert s.get_sum() == pytest.approx(5050.0)


def test_summary_quantile_estimation():
    s = Summary(
        "rpc_duration_seconds",
        "RPC duration",
        quantiles=[0.5, 0.99],
    )
    for i in range(1, 1001):
        s.observe(float(i))
    q50 = s.get_quantile(0.5)
    q99 = s.get_quantile(0.99)
    assert 450 < q50 < 550
    assert 950 < q99 < 1000


# ── Registry ──────────────────────────────────────────────────────────


def test_registry_register_and_collect():
    reg = MetricsRegistry()
    c = Counter("hits_total", "Hits")
    reg.register(c)
    c.inc(42)
    metrics = reg.collect()
    assert len(metrics) == 1
    assert metrics[0].name == "hits_total"
    assert metrics[0].get() == 42


def test_registry_duplicate_name_raises():
    reg = MetricsRegistry()
    reg.register(Counter("dup", "first"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(Counter("dup", "second"))


def test_registry_unregister():
    reg = MetricsRegistry()
    g = Gauge("temp", "temp")
    reg.register(g)
    reg.unregister(g)
    assert reg.collect() == []


# ── HTTP Exporter ─────────────────────────────────────────────────────


def test_http_exporter_serves_metrics():
    reg = MetricsRegistry()
    c = Counter("http_requests_total", "HTTP requests")
    reg.register(c)
    c.inc(7)

    start_http_server(reg, port=0)
    time.sleep(0.1)

    # Find the actual port from the server thread
    from src.core.metrics import _http_server_instance

    port = _http_server_instance.server_address[1]
    url = f"http://127.0.0.1:{port}/metrics"
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = resp.read().decode()

    assert "http_requests_total" in body
    assert "7" in body
