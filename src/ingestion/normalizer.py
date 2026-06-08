"""
AegisAI Ingestion Normalizer
Converts raw log/metric payloads from any source into AegisAI's internal format.
"""

from datetime import datetime, timezone
from typing import Any


def _ensure_iso(ts: Any) -> str:
    """Best-effort timestamp normalization to ISO-8601 UTC."""
    if not ts:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(ts, (int, float)):
        # Unix epoch — seconds or milliseconds
        if ts > 1e12:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(ts)


def normalize_log(entry: dict, source: str = "raw") -> dict:
    """
    Normalize a single log entry to AegisAI internal format.

    Internal format:
        timestamp: str (ISO-8601)
        level:     str (DEBUG / INFO / WARNING / ERROR / CRITICAL)
        message:   str
        service:   str
        trace_id:  str | None
        source:    str   (cloudwatch | datadog | raw)
        metadata:  dict
    """
    level_map = {
        "warn": "WARNING",
        "warning": "WARNING",
        "err": "ERROR",
        "error": "ERROR",
        "crit": "CRITICAL",
        "critical": "CRITICAL",
        "fatal": "CRITICAL",
        "debug": "DEBUG",
        "info": "INFO",
    }

    raw_level = str(
        entry.get("level")
        or entry.get("severity")
        or entry.get("logLevel")
        or entry.get("status")
        or "INFO"
    ).lower()

    return {
        "timestamp": _ensure_iso(
            entry.get("timestamp")
            or entry.get("time")
            or entry.get("date")
            or entry.get("@timestamp")
        ),
        "level": level_map.get(raw_level, raw_level.upper()),
        "message": str(
            entry.get("message")
            or entry.get("msg")
            or entry.get("log")
            or entry.get("text")
            or ""
        ),
        "service": str(
            entry.get("service")
            or entry.get("source")
            or entry.get("app")
            or entry.get("host")
            or "unknown"
        ),
        "trace_id": entry.get("trace_id") or entry.get("traceId") or entry.get("requestId"),
        "source": source,
        "metadata": {
            k: v for k, v in entry.items()
            if k not in ("timestamp", "time", "date", "@timestamp",
                         "level", "severity", "logLevel", "status",
                         "message", "msg", "log", "text",
                         "service", "source", "app", "host",
                         "trace_id", "traceId", "requestId")
        },
    }


def normalize_metric(entry: dict, source: str = "raw") -> dict:
    """
    Normalize a single metric entry to AegisAI internal format.

    Internal format:
        timestamp: str (ISO-8601)
        name:      str
        value:     float
        service:   str
        unit:      str | None
        source:    str
        tags:      dict
    """
    return {
        "timestamp": _ensure_iso(
            entry.get("timestamp")
            or entry.get("time")
            or entry.get("@timestamp")
        ),
        "name": str(
            entry.get("name")
            or entry.get("metric")
            or entry.get("metricName")
            or entry.get("MetricName")
            or "unknown_metric"
        ),
        "value": float(
            entry.get("value")
            or entry.get("Value")
            or entry.get("sum")
            or entry.get("average")
            or entry.get("Average")
            or 0.0
        ),
        "service": str(
            entry.get("service")
            or entry.get("host")
            or entry.get("source")
            or entry.get("Namespace", "").split("/")[-1]
            or "unknown"
        ),
        "unit": entry.get("unit") or entry.get("Unit"),
        "source": source,
        "tags": {
            k: v for k, v in entry.items()
            if k not in ("timestamp", "time", "@timestamp",
                         "name", "metric", "metricName", "MetricName",
                         "value", "Value", "sum", "average", "Average",
                         "service", "host", "source", "Namespace",
                         "unit", "Unit")
        },
    }