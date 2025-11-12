from __future__ import annotations

import logging
from typing import Optional

try:
    from prometheus_client import Counter, Gauge, start_http_server

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    PROMETHEUS_AVAILABLE = False

from schema import ModerationDecision, ModerationEvent

logger = logging.getLogger(__name__)

if PROMETHEUS_AVAILABLE:
    _events_total = Counter(
        "content_moderation_events_total",
        "Number of moderation events received",
        labelnames=["task"],
    )

    _decisions_total = Counter(
        "content_moderation_decisions_total",
        "Number of moderation decisions produced",
        labelnames=["status", "severity"],
    )

    _flags_total = Counter(
        "content_moderation_flags_total",
        "Number of flagged content items",
        labelnames=["severity"],
    )

    _processing_gauge = Gauge(
        "content_moderation_processing_in_progress",
        "Number of events currently being processed",
    )
else:
    _events_total = None
    _decisions_total = None
    _flags_total = None
    _processing_gauge = None

_metrics_started = False


def start_metrics_server(port: int = 9102) -> None:
    global _metrics_started
    if not PROMETHEUS_AVAILABLE:
        if not _metrics_started:
            logger.warning(
                "prometheus_client not installed; metrics server not started. Install prometheus-client to expose metrics."
            )
            _metrics_started = True
        return
    if _metrics_started:
        return
    try:
        start_http_server(port)
        logger.info("Prometheus metrics server started on port %s", port)
        _metrics_started = True
    except OSError as exc:  # pragma: no cover - port in use
        logger.warning("Could not start metrics server on port %s: %s", port, exc)


def record_event(event: ModerationEvent) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    _events_total.labels(task=event.task).inc()
    _processing_gauge.inc()


def record_decision(decision: ModerationDecision) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    status = decision.status or "unknown"
    severity = decision.severity or "none"
    _decisions_total.labels(status=status, severity=severity).inc()
    if status in {"flagged", "removed"}:
        _flags_total.labels(severity=severity).inc()
    try:
        _processing_gauge.dec()
    except ValueError:  # pragma: no cover - guard against negative gauge
        logger.debug("Processing gauge already at zero; skip decrement")


__all__ = ["start_metrics_server", "record_event", "record_decision"]
