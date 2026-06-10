"""
Tests for AegisAI Knowledge Graph — IncidentKnowledgeGraph and build_graph_from_investigation.
"""

import pytest
from src.graph.knowledge_graph import IncidentKnowledgeGraph, build_graph_from_investigation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_graph():
    """Single-incident graph with two services and one anomaly."""
    g = IncidentKnowledgeGraph("INC-TEST-001")
    g.add_service("payments")
    g.add_service("api-gateway")
    g.add_anomaly(
        {"service": "payments", "type": "error_rate_spike", "severity": "critical",
         "detail": "80% error rate", "timestamp": "2026-06-09T10:00:00Z"},
        idx=0,
    )
    g.add_dependency_edges([{"source": "api-gateway", "target": "payments", "relation": "calls"}])
    return g


@pytest.fixture
def full_investigation_result():
    return {
        "incident_id": "INC-FULL-001",
        "affected_services": ["payments", "api-gateway", "db"],
        "anomalies": [
            {"service": "payments", "type": "error_rate_spike", "severity": "critical",
             "detail": "70% errors", "timestamp": "2026-06-09T10:00:00Z"},
            {"service": "db", "type": "metric_spike", "severity": "high",
             "detail": "connection pool exhausted", "timestamp": "2026-06-09T09:58:00Z"},
        ],
        "knowledge_graph_edges": [
            {"source": "api-gateway", "target": "payments", "relation": "calls"},
            {"source": "payments", "target": "db", "relation": "calls"},
        ],
        "causal_chain": ["db", "payments", "api-gateway"],
        "root_cause": "DB connection pool exhaustion caused cascading failures.",
    }


# ---------------------------------------------------------------------------
# Node creation
# ---------------------------------------------------------------------------

class TestNodeCreation:

    def test_incident_node_exists_on_init(self):
        g = IncidentKnowledgeGraph("INC-INIT-001")
        assert g.G.has_node("INC-INIT-001")
        assert g.G.nodes["INC-INIT-001"]["node_type"] == "incident"

    def test_add_service_creates_node(self):
        g = IncidentKnowledgeGraph("INC-SVC-001")
        node_id = g.add_service("checkout")
        assert g.G.has_node(node_id)
        assert g.G.nodes[node_id]["service_name"] == "checkout"
        assert g.G.nodes[node_id]["node_type"] == "service"

    def test_add_service_idempotent(self):
        g = IncidentKnowledgeGraph("INC-IDEM-001")
        n1 = g.add_service("payments")
        n2 = g.add_service("payments")
        assert n1 == n2
        assert g.G.number_of_nodes() == 2  # incident + one service

    def test_add_service_creates_affects_edge(self):
        g = IncidentKnowledgeGraph("INC-EDGE-001")
        node_id = g.add_service("worker")
        assert g.G.has_edge("INC-EDGE-001", node_id)
        assert g.G["INC-EDGE-001"][node_id]["relation"] == "AFFECTS"

    def test_add_anomaly_creates_node_and_edge(self):
        g = IncidentKnowledgeGraph("INC-ANOM-001")
        anom_node = g.add_anomaly(
            {"service": "payments", "type": "error_spike", "severity": "high", "detail": "x"},
            idx=0,
        )
        assert g.G.has_node(anom_node)
        assert g.G.nodes[anom_node]["node_type"] == "anomaly"
        # Anomaly → service edge
        svc_node = g._service_node_id("payments")
        assert g.G.has_edge(anom_node, svc_node)
        assert g.G[anom_node][svc_node]["relation"] == "DETECTED_IN"

    def test_add_anomaly_increments_service_counter(self):
        g = IncidentKnowledgeGraph("INC-CTR-001")
        g.add_anomaly({"service": "api", "type": "spike", "severity": "high"}, idx=0)
        g.add_anomaly({"service": "api", "type": "error", "severity": "medium"}, idx=1)
        svc_node = g._service_node_id("api")
        assert g.G.nodes[svc_node]["anomaly_count"] == 2

    def test_add_anomaly_unknown_service_creates_service(self):
        g = IncidentKnowledgeGraph("INC-UNKN-001")
        g.add_anomaly({"service": "mystery-svc", "type": "x", "severity": "low"}, idx=0)
        assert g.G.has_node(g._service_node_id("mystery-svc"))


# ---------------------------------------------------------------------------
# Dependency edges
# ---------------------------------------------------------------------------

class TestDependencyEdges:

    def test_calls_edge_added(self):
        g = IncidentKnowledgeGraph("INC-DEP-001")
        g.add_dependency_edges([{"source": "api", "target": "payments", "relation": "calls"}])
        api_node = g._service_node_id("api")
        pay_node = g._service_node_id("payments")
        assert g.G.has_edge(api_node, pay_node)
        assert g.G[api_node][pay_node]["relation"] == "CALLS"

    def test_duplicate_edges_accumulate_call_count(self):
        g = IncidentKnowledgeGraph("INC-DUP-001")
        edges = [
            {"source": "api", "target": "payments", "relation": "calls"},
            {"source": "api", "target": "payments", "relation": "calls"},
            {"source": "api", "target": "payments", "relation": "calls"},
        ]
        g.add_dependency_edges(edges)
        api_node = g._service_node_id("api")
        pay_node = g._service_node_id("payments")
        assert g.G[api_node][pay_node]["call_count"] == 3

    def test_empty_edges_list_no_error(self):
        g = IncidentKnowledgeGraph("INC-EMP-001")
        g.add_dependency_edges([])
        assert g.G.number_of_nodes() == 1  # only incident node


# ---------------------------------------------------------------------------
# Root cause marking
# ---------------------------------------------------------------------------

class TestRootCause:

    def test_mark_root_cause_sets_flag(self):
        g = IncidentKnowledgeGraph("INC-RC-001")
        g.add_service("db")
        g.mark_root_cause("db")
        svc_node = g._service_node_id("db")
        assert g.G.nodes[svc_node].get("is_root_cause") is True

    def test_mark_root_cause_changes_color(self):
        g = IncidentKnowledgeGraph("INC-RC-002")
        g.add_service("db")
        g.mark_root_cause("db")
        svc_node = g._service_node_id("db")
        assert g.G.nodes[svc_node]["color"] == "#8E44AD"

    def test_mark_root_cause_updates_edge_relation(self):
        g = IncidentKnowledgeGraph("INC-RC-003")
        g.add_service("db")
        g.mark_root_cause("db")
        svc_node = g._service_node_id("db")
        assert g.G[g.incident_id][svc_node]["relation"] == "ROOT_CAUSE"

    def test_mark_nonexistent_service_no_crash(self):
        g = IncidentKnowledgeGraph("INC-RC-004")
        g.mark_root_cause("ghost-service")  # should not raise


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class TestAnalytics:

    def test_blast_radius_sorted_by_impact(self, simple_graph):
        blast = simple_graph.get_blast_radius()
        assert len(blast) == 2
        # payments has an anomaly, api-gateway does not → payments should rank higher
        assert blast[0]["service"] == "payments"

    def test_blast_radius_root_cause_flagged(self, simple_graph):
        simple_graph.mark_root_cause("payments")
        blast = simple_graph.get_blast_radius()
        payments_entry = next(b for b in blast if b["service"] == "payments")
        assert payments_entry["is_root_cause"] is True

    def test_blast_radius_excludes_incident_node(self, simple_graph):
        blast = simple_graph.get_blast_radius()
        services = [b["service"] for b in blast]
        assert "INC-TEST-001" not in services

    def test_critical_path_returns_list(self, simple_graph):
        path = simple_graph.get_critical_path()
        assert isinstance(path, list)

    def test_critical_path_follows_calls_edges(self):
        g = IncidentKnowledgeGraph("INC-PATH-001")
        g.add_dependency_edges([
            {"source": "frontend", "target": "api", "relation": "calls"},
            {"source": "api", "target": "db", "relation": "calls"},
        ])
        path = g.get_critical_path()
        # Should include nodes in the CALLS subgraph
        assert len(path) >= 2

    def test_critical_path_empty_when_no_calls(self):
        g = IncidentKnowledgeGraph("INC-PATH-002")
        g.add_service("payments")
        assert g.get_critical_path() == []


# ---------------------------------------------------------------------------
# Export formats
# ---------------------------------------------------------------------------

class TestExports:

    def test_to_dict_structure(self, simple_graph):
        data = simple_graph.to_dict()
        assert "incident_id" in data
        assert "node_count" in data
        assert "edge_count" in data
        assert "nodes" in data
        assert "edges" in data
        assert "blast_radius" in data
        assert "critical_path" in data
        assert data["node_count"] == simple_graph.G.number_of_nodes()
        assert data["edge_count"] == simple_graph.G.number_of_edges()

    def test_to_dict_nodes_have_ids(self, simple_graph):
        data = simple_graph.to_dict()
        for node in data["nodes"]:
            assert "id" in node
            assert "node_type" in node

    def test_to_dict_edges_have_source_target(self, simple_graph):
        data = simple_graph.to_dict()
        for edge in data["edges"]:
            assert "source" in edge
            assert "target" in edge

    def test_to_mermaid_contains_graph_td(self, simple_graph):
        mermaid = simple_graph.to_mermaid()
        assert "graph TD" in mermaid

    def test_to_mermaid_contains_service_names(self, simple_graph):
        mermaid = simple_graph.to_mermaid()
        assert "payments" in mermaid
        assert "api-gateway" in mermaid

    def test_to_mermaid_contains_edge_relations(self, simple_graph):
        mermaid = simple_graph.to_mermaid()
        assert "-->" in mermaid

    def test_to_dot_is_valid_digraph(self, simple_graph):
        dot = simple_graph.to_dot()
        assert "digraph" in dot
        assert "rankdir=LR" in dot
        assert "->" in dot

    def test_to_dot_contains_node_labels(self, simple_graph):
        dot = simple_graph.to_dot()
        assert "payments" in dot

    def test_empty_graph_exports_cleanly(self):
        g = IncidentKnowledgeGraph("INC-EMPTY-001")
        data = g.to_dict()
        assert data["node_count"] == 1
        assert data["blast_radius"] == []
        assert g.to_mermaid() != ""
        assert "digraph" in g.to_dot()


# ---------------------------------------------------------------------------
# Factory — build_graph_from_investigation
# ---------------------------------------------------------------------------

class TestBuildGraphFromInvestigation:

    def test_builds_correct_node_count(self, full_investigation_result):
        g = build_graph_from_investigation(full_investigation_result)
        # incident(1) + services(3) + anomalies(2) = 6
        assert g.G.number_of_nodes() == 6

    def test_root_cause_service_flagged(self, full_investigation_result):
        g = build_graph_from_investigation(full_investigation_result)
        svc_node = g._service_node_id("db")
        assert g.G.nodes[svc_node].get("is_root_cause") is True

    def test_all_services_present(self, full_investigation_result):
        g = build_graph_from_investigation(full_investigation_result)
        for svc in ["payments", "api-gateway", "db"]:
            assert g.G.has_node(g._service_node_id(svc))

    def test_dependency_edges_present(self, full_investigation_result):
        g = build_graph_from_investigation(full_investigation_result)
        api_node = g._service_node_id("api-gateway")
        pay_node = g._service_node_id("payments")
        assert g.G.has_edge(api_node, pay_node)

    def test_blast_radius_non_empty(self, full_investigation_result):
        g = build_graph_from_investigation(full_investigation_result)
        assert len(g.get_blast_radius()) == 3

    def test_missing_incident_id_defaults(self):
        result = {"affected_services": [], "anomalies": [], "knowledge_graph_edges": [], "causal_chain": []}
        g = build_graph_from_investigation(result)
        assert "INC-UNKNOWN" in g.incident_id