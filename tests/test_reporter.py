"""
Tests for AegisAI Incident Reporter — Markdown, JSON, and generate_report.
"""

import json
import pytest
from src.graph.knowledge_graph import build_graph_from_investigation
from src.reporter.report import generate_markdown, generate_json, generate_report, _confidence_label


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_result():
    return {
        "incident_id": "INC-RPT-001",
        "root_cause": "Database connection pool exhaustion caused payment service failures.",
        "confidence": 0.87,
        "summary": "A spike in DB connections at 10:00 UTC caused payment failures. "
                   "Checkout and API gateway were affected downstream. "
                   "Scaling the DB connection pool resolved the issue.",
        "affected_services": ["payments", "api-gateway", "db"],
        "causal_chain": ["db", "payments", "api-gateway"],
        "anomalies": [
            {
                "type": "error_rate_spike",
                "service": "payments",
                "severity": "critical",
                "detail": "75% error rate",
                "timestamp": "2026-06-09T10:00:00Z",
            },
            {
                "type": "metric_spike",
                "service": "db",
                "severity": "high",
                "detail": "connection pool at 99%",
                "timestamp": "2026-06-09T09:58:00Z",
            },
        ],
        "timeline": [
            {"timestamp": "2026-06-09T09:58:00Z", "service": "db",
             "severity": "high", "event": "Connection pool spike detected"},
            {"timestamp": "2026-06-09T10:00:00Z", "service": "payments",
             "severity": "critical", "event": "Error rate exceeds 75%"},
        ],
        "remediation": [
            "Scale DB connection pool from 50 to 200 connections.",
            "Add connection pool monitoring alert at 80% utilization.",
            "Implement circuit breaker in payments service.",
        ],
        "knowledge_graph_edges": [
            {"source": "api-gateway", "target": "payments", "relation": "calls"},
            {"source": "payments", "target": "db", "relation": "calls"},
        ],
    }


@pytest.fixture
def sample_graph(sample_result):
    return build_graph_from_investigation(sample_result)


@pytest.fixture
def minimal_result():
    """Bare-minimum result with all optional fields empty."""
    return {
        "incident_id": "INC-MIN-001",
        "root_cause": "",
        "confidence": 0.0,
        "summary": "",
        "affected_services": [],
        "causal_chain": [],
        "anomalies": [],
        "timeline": [],
        "remediation": [],
        "knowledge_graph_edges": [],
    }


@pytest.fixture
def minimal_graph(minimal_result):
    return build_graph_from_investigation(minimal_result)


# ---------------------------------------------------------------------------
# _confidence_label helper
# ---------------------------------------------------------------------------

class TestConfidenceLabel:

    def test_high_confidence(self):
        assert "High" in _confidence_label(0.9)
        assert "High" in _confidence_label(0.8)

    def test_medium_confidence(self):
        assert "Medium" in _confidence_label(0.65)
        assert "Medium" in _confidence_label(0.5)

    def test_low_confidence(self):
        assert "Low" in _confidence_label(0.3)
        assert "Low" in _confidence_label(0.0)

    def test_boundary_exactly_08(self):
        label = _confidence_label(0.8)
        assert "High" in label

    def test_boundary_exactly_05(self):
        label = _confidence_label(0.5)
        assert "Medium" in label


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

class TestGenerateMarkdown:

    def test_returns_string(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert isinstance(md, str)
        assert len(md) > 100

    def test_contains_incident_id(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "INC-RPT-001" in md

    def test_contains_root_cause_section(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "Root Cause" in md
        assert "connection pool" in md.lower()

    def test_contains_executive_summary(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "Executive Summary" in md
        assert "DB connections" in md or "spike" in md.lower()

    def test_contains_all_anomaly_services(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "payments" in md
        assert "db" in md

    def test_anomaly_severity_emojis_present(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        # 🔴 for critical, 🟠 for high
        assert "🔴" in md or "🟠" in md

    def test_contains_causal_chain(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "Causal Chain" in md

    def test_contains_blast_radius_table(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "Blast Radius" in md

    def test_contains_remediation_steps(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "Remediation" in md
        assert "connection pool" in md.lower()

    def test_contains_timeline(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "Timeline" in md

    def test_contains_mermaid_block(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "```mermaid" in md

    def test_contains_knowledge_graph_stats(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "Knowledge Graph" in md
        assert "Nodes" in md

    def test_contains_footer_link(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "AegisAI" in md
        assert "github.com" in md

    def test_confidence_percentage_shown(self, sample_result, sample_graph):
        md = generate_markdown(sample_result, sample_graph)
        assert "87%" in md

    def test_minimal_result_no_crash(self, minimal_result, minimal_graph):
        md = generate_markdown(minimal_result, minimal_graph)
        assert isinstance(md, str)
        assert "AegisAI" in md

    def test_missing_summary_shows_placeholder(self, minimal_result, minimal_graph):
        md = generate_markdown(minimal_result, minimal_graph)
        assert "_No summary generated._" in md

    def test_missing_root_cause_graceful(self, minimal_result, minimal_graph):
        md = generate_markdown(minimal_result, minimal_graph)
        assert "Root Cause" in md


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

class TestGenerateJson:

    def test_returns_dict(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert isinstance(data, dict)

    def test_schema_version_present(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert data.get("schema_version") == "1.0"

    def test_generated_at_present(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert "generated_at" in data
        assert "UTC" in data["generated_at"]

    def test_incident_section_complete(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        inc = data["incident"]
        assert inc["id"] == "INC-RPT-001"
        assert inc["root_cause"] == sample_result["root_cause"]
        assert inc["confidence"] == 0.87
        assert "High" in inc["confidence_label"]
        assert inc["affected_services"] == ["payments", "api-gateway", "db"]
        assert inc["causal_chain"] == ["db", "payments", "api-gateway"]

    def test_anomalies_list_correct_length(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert len(data["anomalies"]) == 2

    def test_timeline_list_preserved(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert len(data["timeline"]) == 2

    def test_remediation_list_preserved(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert len(data["remediation"]) == 3

    def test_graph_section_present(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        graph = data["graph"]
        assert "node_count" in graph
        assert "edge_count" in graph
        assert "blast_radius" in graph
        assert "critical_path" in graph
        assert "nodes" in graph
        assert "edges" in graph
        assert "mermaid" in graph
        assert "dot" in graph

    def test_graph_mermaid_valid(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert "graph TD" in data["graph"]["mermaid"]

    def test_graph_dot_valid(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        assert "digraph" in data["graph"]["dot"]

    def test_is_json_serializable(self, sample_result, sample_graph):
        data = generate_json(sample_result, sample_graph)
        serialized = json.dumps(data)
        reparsed = json.loads(serialized)
        assert reparsed["incident"]["id"] == "INC-RPT-001"

    def test_minimal_result_no_crash(self, minimal_result, minimal_graph):
        data = generate_json(minimal_result, minimal_graph)
        assert data["incident"]["id"] == "INC-MIN-001"
        assert data["anomalies"] == []


# ---------------------------------------------------------------------------
# generate_report dispatcher
# ---------------------------------------------------------------------------

class TestGenerateReport:

    def test_fmt_markdown_returns_only_markdown(self, sample_result, sample_graph):
        output = generate_report(sample_result, sample_graph, fmt="markdown")
        assert "markdown" in output
        assert "json" not in output

    def test_fmt_json_returns_only_json(self, sample_result, sample_graph):
        output = generate_report(sample_result, sample_graph, fmt="json")
        assert "json" in output
        assert "markdown" not in output

    def test_fmt_both_returns_both(self, sample_result, sample_graph):
        output = generate_report(sample_result, sample_graph, fmt="both")
        assert "markdown" in output
        assert "json" in output

    def test_markdown_output_is_string(self, sample_result, sample_graph):
        output = generate_report(sample_result, sample_graph, fmt="markdown")
        assert isinstance(output["markdown"], str)

    def test_json_output_is_dict(self, sample_result, sample_graph):
        output = generate_report(sample_result, sample_graph, fmt="json")
        assert isinstance(output["json"], dict)

    def test_default_fmt_is_both(self, sample_result, sample_graph):
        output = generate_report(sample_result, sample_graph)
        assert "markdown" in output
        assert "json" in output