"""APEX-OS Prometheus metrics collector.

Provides Counter, Gauge, Histogram, Summary metric types,
a custom registry, and an HTTP exporter for Prometheus scraping.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


# ── Counter ──────────────────────────────────────────────────────────


class Counter:
    """A monotonically increasing counter metric."""

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: list[str] | None = None,
    ) -> None:
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames or []
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> Counter:
        """Return a child counter with the given label values."""
        key = tuple(kwargs[k] for k in self.labelnames)
        if key not in self._values:
            self._values[key] = 0.0
        child = Counter(self.name, self.documentation, self.labelnames)
        child._values = self._values
        child._key = key
        return child

    def inc(self, value: float = 1.0) -> None:
        """Increment the counter by value (default 1)."""
        if value < 0:
            raise ValueError("Counter cannot be decreased")
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def dec(self) -> None:
        """Decrement is not allowed for counters."""
        raise ValueError("Counter cannot be decreased")

    def get(self) -> float:
        """Get the current counter value."""
        key = getattr(self, "_key", ())
        with self._lock:
            return self._values.get(key, 0.0)


# ── Gauge ─────────────────────────────────────────────────────────────


class Gauge:
    """A gauge metric that can go up and down."""

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: list[str] | None = None,
    ) -> None:
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames or []
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> Gauge:
        """Return a child gauge with the given label values."""
        key = tuple(kwargs[k] for k in self.labelnames)
        if key not in self._values:
            self._values[key] = 0.0
        child = Gauge(self.name, self.documentation, self.labelnames)
        child._values = self._values
        child._key = key
        return child

    def set(self, value: float) -> None:
        """Set the gauge to a specific value."""
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = value

    def inc(self, value: float = 1.0) -> None:
        """Increment the gauge by value."""
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def dec(self, value: float = 1.0) -> None:
        """Decrement the gauge by value."""
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - value

    def get(self) -> float:
        """Get the current gauge value."""
        key = getattr(self, "_key", ())
        with self._lock:
            return self._values.get(key, 0.0)


# ── Histogram ─────────────────────────────────────────────────────────


class Histogram:
    """A histogram metric that samples observations into buckets."""

    def __init__(
        self,
        name: str,
        documentation: str,
        buckets: list[float] | None = None,
        labelnames: list[str] | None = None,
    ) -> None:
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames or []
        self.buckets = sorted(buckets) if buckets else [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        self._bucket_counts: dict[float, int] = {b: 0 for b in self.buckets}
        self._sum: float = 0.0
        self._count: int = 0
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> Histogram:
        """Return a child histogram with the given label values."""
        return self

    def observe(self, value: float) -> None:
        """Record an observation."""
        with self._lock:
            self._count += 1
            self._sum += value
            for bucket in self.buckets:
                if value <= bucket:
                    self._bucket_counts[bucket] += 1

    def get_count(self) -> int:
        """Get the total number of observations."""
        with self._lock:
            return self._count

    def get_sum(self) -> float:
        """Get the sum of all observations."""
        with self._lock:
            return self._sum

    def get_buckets(self) -> dict[float, int]:
        """Get bucket counts including +Inf."""
        with self._lock:
            result = dict(self._bucket_counts)
            result["+Inf"] = self._count
            return result


# ── Summary ───────────────────────────────────────────────────────────


class Summary:
    """A summary metric that tracks quantiles."""

    def __init__(
        self,
        name: str,
        documentation: str,
        quantiles: list[float] | None = None,
        labelnames: list[str] | None = None,
    ) -> None:
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames or []
        self.quantiles = quantiles or [0.5, 0.95, 0.99]
        self._observations: list[float] = []
        self._sum: float = 0.0
        self._count: int = 0
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> Summary:
        """Return a child summary with the given label values."""
        return self

    def observe(self, value: float) -> None:
        """Record an observation."""
        with self._lock:
            self._count += 1
            self._sum += value
            self._observations.append(value)

    def get_count(self) -> int:
        """Get the total number of observations."""
        with self._lock:
            return self._count

    def get_sum(self) -> float:
        """Get the sum of all observations."""
        with self._lock:
            return self._sum

    def get_quantile(self, q: float) -> float:
        """Get the estimated value for the given quantile."""
        with self._lock:
            if not self._observations:
                return 0.0
            sorted_obs = sorted(self._observations)
            idx = int(q * len(sorted_obs))
            if idx >= len(sorted_obs):
                idx = len(sorted_obs) - 1
            return sorted_obs[idx]


# ── Registry ──────────────────────────────────────────────────────────


class MetricsRegistry:
    """A registry for collecting and managing metrics."""

    def __init__(self) -> None:
        self._metrics: dict[str, Any] = {}
        self._lock = threading.Lock()

    def register(self, metric: Any) -> None:
        """Register a metric."""
        with self._lock:
            if metric.name in self._metrics:
                raise ValueError(f"Metric '{metric.name}' already registered")
            self._metrics[metric.name] = metric

    def unregister(self, metric: Any) -> None:
        """Unregister a metric."""
        with self._lock:
            self._metrics.pop(metric.name, None)

    def collect(self) -> list[Any]:
        """Collect all registered metrics."""
        with self._lock:
            return list(self._metrics.values())


# ── HTTP Exporter ─────────────────────────────────────────────────────


_http_server_instance: HTTPServer | None = None


def start_http_server(registry: MetricsRegistry, port: int = 8000, host: str = "0.0.0.0") -> HTTPServer:
    """Start an HTTP server that exposes metrics in Prometheus format."""
    global _http_server_instance

    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/metrics":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.end_headers()
                output = _format_metrics(registry)
                self.wfile.write(output.encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Suppress request logging

    server = HTTPServer((host, port), MetricsHandler)
    _http_server_instance = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _format_metrics(registry: MetricsRegistry) -> str:
    """Format all registered metrics in Prometheus exposition format."""
    lines: list[str] = []
    for metric in registry.collect():
        lines.append(f"# HELP {metric.name} {metric.documentation}")
        lines.append(f"# TYPE {metric.name} {_get_metric_type(metric)}")
        if isinstance(metric, Counter):
            lines.append(f"{metric.name} {metric.get()}")
        elif isinstance(metric, Gauge):
            lines.append(f"{metric.name} {metric.get()}")
        elif isinstance(metric, Histogram):
            for bucket, count in metric.get_buckets().items():
                lines.append(f'{metric.name}_bucket{{le="{bucket}"}} {count}')
            lines.append(f"{metric.name}_sum {metric.get_sum()}")
            lines.append(f"{metric.name}_count {metric.get_count()}")
        elif isinstance(metric, Summary):
            for q in metric.quantiles:
                lines.append(f'{metric.name}{{quantile="{q}"}} {metric.get_quantile(q)}')
            lines.append(f"{metric.name}_sum {metric.get_sum()}")
            lines.append(f"{metric.name}_count {metric.get_count()}")
    return "\n".join(lines) + "\n"


def _get_metric_type(metric: Any) -> str:
    """Get the Prometheus metric type string."""
    if isinstance(metric, Counter):
        return "counter"
    if isinstance(metric, Gauge):
        return "gauge"
    if isinstance(metric, Histogram):
        return "histogram"
    if isinstance(metric, Summary):
        return "summary"
    return "untyped"
