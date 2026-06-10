"""
Tests for AegisAI agent nodes — anomaly detection and dependency correlation.
"""

import pytest
from src.agent.nodes import detect_anomalies, correlate_dependencies


# ---------------------------------------------------------------------------
# detect_anomalies tests
# ---------------------------------------------------------------------------

class TestDetectAnomalies:

    def _make_log(self, service, level, n=1):
        return [
            {
                "timestamp": "2026-06-09T10:00:00Z",
                "level": level,
                "message": f"{level} in {service}",
                "service": service,
            }
            for _ in range(n)
        ]

    def test_no_data_returns_empty(self):
        result = detect_anomalies({"logs": [], "metrics": []})
        assert result["anomalies"] == []
        assert result["affected_services"] == []

    def test_high_error_rate_detected(self):
        logs = self._make_log("payments", "ERROR", 10) + self._make_log("payments", "INFO", 5)
        result = detect_anomalies({"logs": logs, "metrics": []})
        anomalies = result["anomalies"]
        assert len(anomalies) > 0
        assert any(a["service"] == "payments" for a in anomalies)
        assert "payments" in result["affected_services"]

    def test_low_error_rate_not_flagged(self):
        logs = self._make_log("payments", "ERROR", 1) + self._make_log("payments", "INFO", 100)
        result = detect_anomalies({"logs": logs, "metrics": []})
        assert all(a["service"] != "payments" for a in result["anomalies"])

    def test_critical_severity_assigned(self):
        logs = self._make_log("db", "ERROR", 25) + self._make_log("db", "INFO", 5)
        result = detect_anomalies({"logs": logs, "metrics": []})
        db_anomalies = [a for a in result["anomalies"] if a["service"] == "db"]
        assert any(a["severity"] == "critical" for a in db_anomalies)

    def test_metric_spike_detected(self):
        # Need enough stable baseline values so the outlier's z-score exceeds 2.5.
        # 20 stable readings + 1 extreme spike → z-score ≈ 4.5, well above threshold.
        stable = [{"timestamp": "2026-06-09T10:00:00Z", "name": "latency_ms",
                   "value": 100, "service": "api"}] * 20
        spike  = [{"timestamp": "2026-06-09T10:01:00Z", "name": "latency_ms",
                   "value": 5000, "service": "api"}]
        result = detect_anomalies({"logs": [], "metrics": stable + spike})
        assert any(a["service"] == "api" for a in result["anomalies"])

    def test_stable_metrics_not_flagged(self):
        metrics = [
            {"timestamp": "2026-06-09T10:00:00Z", "name": "cpu", "value": v, "service": "worker"}
            for v in [50, 51, 49, 52, 50]
        ]
        result = detect_anomalies({"logs": [], "metrics": metrics})
        assert all(a["service"] != "worker" for a in result["anomalies"])

    def test_multiple_services_independently_evaluated(self):
        logs = (
            self._make_log("svc-a", "ERROR", 10) +
            self._make_log("svc-a", "INFO", 2) +
            self._make_log("svc-b", "INFO", 50)
        )
        result = detect_anomalies({"logs": logs, "metrics": []})
        affected = result["affected_services"]
        assert "svc-a" in affected
        assert "svc-b" not in affected


# ---------------------------------------------------------------------------
# correlate_dependencies tests
# ---------------------------------------------------------------------------

class TestCorrelateDependencies:

    def test_no_logs_returns_empty(self):
        state = {"logs": [], "affected_services": ["payments"]}
        result = correlate_dependencies(state)
        assert result["knowledge_graph_edges"] == []

    def test_dependency_extracted_from_log(self):
        state = {
            "logs": [
                {
                    "timestamp": "2026-06-09T10:00:00Z",
                    "level": "ERROR",
                    "message": "calling payments for checkout",
                    "service": "api-gateway",
                }
            ],
            "affected_services": ["payments"],
        }
        result = correlate_dependencies(state)
        edges = result["knowledge_graph_edges"]
        assert len(edges) > 0
        assert edges[0]["source"] == "api-gateway"

    def test_duplicate_edges_deduplicated(self):
        log = {
            "timestamp": "2026-06-09T10:00:00Z",
            "level": "INFO",
            "message": "calling payments service",
            "service": "checkout",
        }
        state = {"logs": [log, log, log], "affected_services": ["payments"]}
        result = correlate_dependencies(state)
        edges = result["knowledge_graph_edges"]
        pairs = [(e["source"], e["target"]) for e in edges]
        assert len(pairs) == len(set(pairs))

    def test_causal_chain_returned(self):
        state = {
            "logs": [
                {"timestamp": "2026-06-09T10:00:00Z", "level": "ERROR",
                 "message": "calling payments", "service": "checkout"},
            ],
            "affected_services": ["payments", "checkout"],
        }
        result = correlate_dependencies(state)
        assert isinstance(result["causal_chain"], list)


# ---------------------------------------------------------------------------
# Knowledge graph tests
# ---------------------------------------------------------------------------

class TestKnowledgeGraph:

    def test_build_graph_from_investigation(self):
        from src.graph.knowledge_graph import build_graph_from_investigation

        result = {
            "incident_id": "INC-TEST-001",
            "affected_services": ["payments", "api-gateway"],
            "anomalies": [
                {"service": "payments", "type": "error_rate_spike",
                 "severity": "critical", "detail": "80% error rate", "timestamp": "2026-06-09T10:00:00Z"}
            ],
            "knowledge_graph_edges": [
                {"source": "api-gateway", "target": "payments", "relation": "calls"}
            ],
            "causal_chain": ["payments", "api-gateway"],
        }

        g = build_graph_from_investigation(result)
        data = g.to_dict()

        assert data["node_count"] >= 3  # incident + 2 services
        assert data["edge_count"] >= 2
        assert len(data["blast_radius"]) == 2
        assert data["blast_radius"][0]["service"] == "payments"  # highest impact first

    def test_mermaid_export(self):
        from src.graph.knowledge_graph import IncidentKnowledgeGraph
        g = IncidentKnowledgeGraph("INC-MERMAID-001")
        g.add_service("payments")
        g.add_anomaly({"service": "payments", "type": "error_rate_spike", "severity": "high"}, 0)
        mermaid = g.to_mermaid()
        assert "graph TD" in mermaid
        assert "payments" in mermaid

    def test_dot_export(self):
        from src.graph.knowledge_graph import IncidentKnowledgeGraph
        g = IncidentKnowledgeGraph("INC-DOT-001")
        g.add_service("db")
        dot = g.to_dot()
        assert "digraph" in dot
        assert "db" in dot