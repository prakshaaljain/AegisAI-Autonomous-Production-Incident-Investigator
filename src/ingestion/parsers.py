"""
AegisAI Ingestion Parsers
Source-specific parsers for CloudWatch, Datadog, and generic JSON payloads.
Each parser returns (logs, metrics) as lists of normalized dicts.
"""

import json
import logging
from typing import Any

from .normalizer import normalize_log, normalize_metric

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic / Raw JSON
# ---------------------------------------------------------------------------

def parse_raw(payload: dict) -> tuple[list[dict], list[dict]]:
    """
    Parse a generic AegisAI payload:
    {
        "logs":    [ { "timestamp": ..., "level": ..., "message": ..., "service": ... } ],
        "metrics": [ { "timestamp": ..., "name": ..., "value": ..., "service": ... } ]
    }
    """
    logs = [normalize_log(e, source="raw") for e in payload.get("logs", [])]
    metrics = [normalize_metric(e, source="raw") for e in payload.get("metrics", [])]
    logger.info(f"[parse_raw] {len(logs)} logs, {len(metrics)} metrics")
    return logs, metrics


# ---------------------------------------------------------------------------
# AWS CloudWatch
# ---------------------------------------------------------------------------

def parse_cloudwatch_logs(cw_payload: dict) -> list[dict]:
    """
    Parse CloudWatch Logs Insights query results or log event batches.

    Supports two formats:
    1. Insights results: { "results": [ [ {"field": "...", "value": "..."} ] ] }
    2. Log events:       { "events": [ {"timestamp": ..., "message": "..."} ], "logStreamName": "..." }
    """
    logs = []

    # Format 1 — Insights results
    if "results" in cw_payload:
        for row in cw_payload["results"]:
            entry: dict[str, Any] = {}
            for field_obj in row:
                entry[field_obj.get("field", "").lstrip("@")] = field_obj.get("value", "")
            logs.append(normalize_log(entry, source="cloudwatch"))

    # Format 2 — Log event batch
    elif "events" in cw_payload:
        stream = cw_payload.get("logStreamName", "")
        group = cw_payload.get("logGroupName", "")
        for event in cw_payload["events"]:
            raw_msg = event.get("message", "")
            # Try to parse structured JSON embedded in the message
            try:
                structured = json.loads(raw_msg)
            except (json.JSONDecodeError, TypeError):
                structured = {"message": raw_msg}

            structured.setdefault("service", stream or group or "cloudwatch")
            structured.setdefault("timestamp", event.get("timestamp"))
            logs.append(normalize_log(structured, source="cloudwatch"))

    logger.info(f"[parse_cloudwatch_logs] {len(logs)} log entries")
    return logs


def parse_cloudwatch_metrics(cw_payload: dict) -> list[dict]:
    """
    Parse CloudWatch GetMetricData response:
    {
        "MetricDataResults": [
            {
                "Id": "cpu",
                "Label": "CPUUtilization",
                "Timestamps": [...],
                "Values": [...],
                "StatusCode": "Complete"
            }
        ]
    }
    """
    metrics = []
    for result in cw_payload.get("MetricDataResults", []):
        label = result.get("Label", result.get("Id", "unknown"))
        namespace = cw_payload.get("Namespace", "")
        service = namespace.split("/")[-1] if namespace else label

        timestamps = result.get("Timestamps", [])
        values = result.get("Values", [])

        for ts, val in zip(timestamps, values):
            metrics.append(normalize_metric({
                "timestamp": ts,
                "name": label,
                "value": val,
                "service": service,
                "Namespace": namespace,
            }, source="cloudwatch"))

    logger.info(f"[parse_cloudwatch_metrics] {len(metrics)} metric points")
    return metrics


# ---------------------------------------------------------------------------
# Datadog
# ---------------------------------------------------------------------------

def parse_datadog_logs(dd_payload: dict) -> list[dict]:
    """
    Parse Datadog Log Search API response:
    {
        "data": [
            {
                "id": "...",
                "attributes": {
                    "timestamp": "...",
                    "status": "error",
                    "message": "...",
                    "service": "...",
                    "tags": ["env:prod", "version:1.2"],
                    "attributes": { ... }
                }
            }
        ]
    }
    """
    logs = []
    for item in dd_payload.get("data", []):
        attrs = item.get("attributes", {})
        extra = attrs.get("attributes", {})

        entry = {
            "timestamp": attrs.get("timestamp"),
            "level": attrs.get("status", "info"),
            "message": attrs.get("message", ""),
            "service": attrs.get("service", extra.get("host", "unknown")),
            "trace_id": extra.get("trace_id") or extra.get("dd.trace_id"),
        }

        # Parse tags list → metadata
        for tag in attrs.get("tags", []):
            if ":" in tag:
                k, v = tag.split(":", 1)
                entry[k] = v

        logs.append(normalize_log(entry, source="datadog"))

    logger.info(f"[parse_datadog_logs] {len(logs)} log entries")
    return logs


def parse_datadog_metrics(dd_payload: dict) -> list[dict]:
    """
    Parse Datadog Metrics Query API response:
    {
        "series": [
            {
                "metric": "system.cpu.user",
                "display_name": "system.cpu.user",
                "scope": "service:payments",
                "pointlist": [[epoch_ms, value], ...]
            }
        ]
    }
    """
    metrics = []
    for series in dd_payload.get("series", []):
        metric_name = series.get("metric", "unknown")
        scope = series.get("scope", "")

        # Extract service from scope tag
        service = "unknown"
        for tag in scope.split(","):
            tag = tag.strip()
            if tag.startswith("service:"):
                service = tag.split(":", 1)[1]
                break

        unit = None
        if series.get("unit"):
            unit_info = series["unit"]
            if isinstance(unit_info, list) and unit_info:
                unit = unit_info[0].get("short_name")

        for point in series.get("pointlist", []):
            if len(point) == 2:
                ts_ms, val = point
                metrics.append(normalize_metric({
                    "timestamp": ts_ms,
                    "name": metric_name,
                    "value": val if val is not None else 0.0,
                    "service": service,
                    "unit": unit,
                }, source="datadog"))

    logger.info(f"[parse_datadog_metrics] {len(metrics)} metric points")
    return metrics


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

SOURCES = {"raw", "cloudwatch", "datadog"}


def ingest(source: str, payload: dict) -> tuple[list[dict], list[dict]]:
    """
    Unified ingestion entry point.

    Args:
        source:  One of 'raw', 'cloudwatch', 'datadog'
        payload: Raw API payload from the source

    Returns:
        (logs, metrics) — both as lists of normalized dicts
    """
    source = source.lower().strip()

    if source == "raw":
        return parse_raw(payload)

    elif source == "cloudwatch":
        logs = parse_cloudwatch_logs(payload) if "results" in payload or "events" in payload else []
        metrics = parse_cloudwatch_metrics(payload) if "MetricDataResults" in payload else []
        return logs, metrics

    elif source == "datadog":
        logs = parse_datadog_logs(payload) if "data" in payload else []
        metrics = parse_datadog_metrics(payload) if "series" in payload else []
        return logs, metrics

    else:
        raise ValueError(f"Unknown source '{source}'. Valid sources: {SOURCES}")