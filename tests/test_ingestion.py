"""
Tests for AegisAI ingestion layer — normalizer and parsers.
"""

import pytest
from src.ingestion.normalizer import normalize_log, normalize_metric
from src.ingestion.parsers import ingest, parse_cloudwatch_logs, parse_datadog_logs


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

class TestNormalizeLog:

    def test_basic_fields(self):
        entry = {
            "timestamp": "2026-06-09T10:00:00Z",
            "level": "error",
            "message": "Something broke",
            "service": "payments",
        }
        result = normalize_log(entry)
        assert result["level"] == "ERROR"
        assert result["message"] == "Something broke"
        assert result["service"] == "payments"
        assert result["source"] == "raw"

    def test_level_aliases(self):
        assert normalize_log({"level": "warn"})["level"] == "WARNING"
        assert normalize_log({"level": "fatal"})["level"] == "CRITICAL"
        assert normalize_log({"level": "crit"})["level"] == "CRITICAL"
        assert normalize_log({"level": "err"})["level"] == "ERROR"

    def test_missing_fields_get_defaults(self):
        result = normalize_log({})
        assert result["level"] == "INFO"
        assert result["service"] == "unknown"
        assert result["message"] == ""
        assert result["source"] == "raw"

    def test_unix_timestamp_seconds(self):
        result = normalize_log({"timestamp": 1700000000})
        assert "2023" in result["timestamp"]

    def test_unix_timestamp_milliseconds(self):
        result = normalize_log({"timestamp": 1700000000000})
        assert "2023" in result["timestamp"]

    def test_alternate_field_names(self):
        entry = {"msg": "hello", "severity": "DEBUG", "app": "worker", "@timestamp": "2026-01-01T00:00:00Z"}
        result = normalize_log(entry)
        assert result["message"] == "hello"
        assert result["level"] == "DEBUG"
        assert result["service"] == "worker"

    def test_trace_id_extracted(self):
        entry = {"message": "ok", "traceId": "abc-123"}
        result = normalize_log(entry)
        assert result["trace_id"] == "abc-123"

    def test_extra_fields_go_to_metadata(self):
        entry = {"message": "ok", "service": "api", "env": "prod", "region": "us-east-1"}
        result = normalize_log(entry)
        assert result["metadata"]["env"] == "prod"
        assert result["metadata"]["region"] == "us-east-1"

    def test_source_label_preserved(self):
        result = normalize_log({"message": "x"}, source="cloudwatch")
        assert result["source"] == "cloudwatch"


class TestNormalizeMetric:

    def test_basic_fields(self):
        entry = {
            "timestamp": "2026-06-09T10:00:00Z",
            "name": "cpu_usage",
            "value": 92.5,
            "service": "worker",
        }
        result = normalize_metric(entry)
        assert result["name"] == "cpu_usage"
        assert result["value"] == 92.5
        assert result["service"] == "worker"

    def test_missing_value_defaults_to_zero(self):
        result = normalize_metric({"name": "latency"})
        assert result["value"] == 0.0

    def test_alternate_value_fields(self):
        result = normalize_metric({"name": "req", "Average": 45.0})
        assert result["value"] == 45.0

    def test_cloudwatch_namespace_as_service(self):
        entry = {"name": "CPUUtilization", "value": 80.0, "Namespace": "AWS/EC2"}
        result = normalize_metric(entry, source="cloudwatch")
        assert result["service"] == "EC2"

    def test_tags_captured(self):
        entry = {"name": "rps", "value": 100, "service": "api", "env": "prod"}
        result = normalize_metric(entry)
        assert result["tags"]["env"] == "prod"


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseRaw:

    def test_empty_payload(self):
        logs, metrics = ingest("raw", {})
        assert logs == []
        assert metrics == []

    def test_logs_and_metrics_parsed(self):
        payload = {
            "logs": [
                {"timestamp": "2026-06-09T10:00:00Z", "level": "ERROR",
                 "message": "DB timeout", "service": "payments"}
            ],
            "metrics": [
                {"timestamp": "2026-06-09T10:00:00Z", "name": "error_rate",
                 "value": 0.9, "service": "payments"}
            ]
        }
        logs, metrics = ingest("raw", payload)
        assert len(logs) == 1
        assert len(metrics) == 1
        assert logs[0]["level"] == "ERROR"
        assert metrics[0]["value"] == 0.9

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError, match="Unknown source"):
            ingest("splunk", {})


class TestParseCloudwatch:

    def test_insights_format(self):
        payload = {
            "results": [
                [
                    {"field": "@timestamp", "value": "2026-06-09T10:00:00Z"},
                    {"field": "@message", "value": "Connection refused"},
                    {"field": "@logStream", "value": "payments-service"},
                ]
            ]
        }
        logs = parse_cloudwatch_logs(payload)
        assert len(logs) == 1
        assert logs[0]["source"] == "cloudwatch"

    def test_events_format_with_json_message(self):
        payload = {
            "logGroupName": "prod-payments",
            "events": [
                {
                    "timestamp": 1700000000000,
                    "message": '{"level": "ERROR", "message": "Timeout", "service": "payments"}'
                }
            ]
        }
        logs = parse_cloudwatch_logs(payload)
        assert len(logs) == 1
        assert logs[0]["level"] == "ERROR"

    def test_events_format_plain_text(self):
        payload = {
            "logStreamName": "api-gateway",
            "events": [
                {"timestamp": 1700000000000, "message": "Plain text error log"}
            ]
        }
        logs = parse_cloudwatch_logs(payload)
        assert len(logs) == 1
        assert logs[0]["message"] == "Plain text error log"
        assert logs[0]["service"] == "api-gateway"


class TestParseDatadog:

    def test_basic_log_parsing(self):
        payload = {
            "data": [
                {
                    "id": "abc123",
                    "attributes": {
                        "timestamp": "2026-06-09T10:00:00Z",
                        "status": "error",
                        "message": "Payment failed",
                        "service": "payments",
                        "tags": ["env:prod", "version:1.2"],
                        "attributes": {}
                    }
                }
            ]
        }
        logs = parse_datadog_logs(payload)
        assert len(logs) == 1
        assert logs[0]["level"] == "ERROR"
        assert logs[0]["service"] == "payments"
        assert logs[0]["source"] == "datadog"

    def test_tags_parsed_to_metadata(self):
        payload = {
            "data": [
                {
                    "attributes": {
                        "status": "info",
                        "message": "ok",
                        "service": "api",
                        "tags": ["env:staging", "region:us-west"],
                        "attributes": {}
                    }
                }
            ]
        }
        logs = parse_datadog_logs(payload)
        assert logs[0]["metadata"].get("env") == "staging"

    def test_empty_data(self):
        logs = parse_datadog_logs({"data": []})
        assert logs == []