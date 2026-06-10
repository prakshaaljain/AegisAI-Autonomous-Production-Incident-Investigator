"""
AegisAI Knowledge Graph
Builds a NetworkX directed graph from agent-discovered service dependencies,
anomalies, and causal chains. Exports to JSON (for API), DOT (for Graphviz),
and Mermaid (for README/docs).
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

import networkx as nx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node / Edge attribute constants
# ---------------------------------------------------------------------------

NODE_TYPES = {
    "service":  {"color": "#4A90D9", "shape": "ellipse"},
    "anomaly":  {"color": "#E74C3C", "shape": "diamond"},
    "incident": {"color": "#F39C12", "shape": "box"},
}

SEVERITY_WEIGHT = {
    "critical": 4,
    "high":     3,
    "medium":   2,
    "low":      1,
    "unknown":  1,
}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class IncidentKnowledgeGraph:
    """
    Directed graph representing a single incident investigation.

    Nodes:
        - incident  (one per investigation)
        - service   (one per unique service name)
        - anomaly   (one per detected anomaly)

    Edges:
        - incident  → service   (AFFECTS)
        - service   → service   (CALLS, from log co-occurrence)
        - anomaly   → service   (DETECTED_IN)
        - service   → anomaly   (ROOT_CAUSE_OF, for causal-chain root)
    """

    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self.G: nx.DiGraph = nx.DiGraph()
        self._add_incident_node()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_incident_node(self):
        self.G.add_node(
            self.incident_id,
            node_type="incident",
            label=self.incident_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            **NODE_TYPES["incident"],
        )

    def _service_node_id(self, service: str) -> str:
        return f"svc:{service}"

    def _anomaly_node_id(self, anomaly: dict, idx: int) -> str:
        svc = anomaly.get("service", "unknown")
        atype = anomaly.get("type", "anomaly")
        return f"anom:{svc}:{atype}:{idx}"

    # ------------------------------------------------------------------
    # Public build API
    # ------------------------------------------------------------------

    def add_service(self, service: str, metadata: Optional[dict] = None) -> str:
        node_id = self._service_node_id(service)
        if not self.G.has_node(node_id):
            self.G.add_node(
                node_id,
                node_type="service",
                label=service,
                service_name=service,
                anomaly_count=0,
                error_count=0,
                **(metadata or {}),
                **NODE_TYPES["service"],
            )
            self.G.add_edge(
                self.incident_id, node_id,
                relation="AFFECTS",
                weight=1,
            )
        return node_id

    def add_anomaly(self, anomaly: dict, idx: int) -> str:
        svc = anomaly.get("service", "unknown")
        svc_node = self.add_service(svc)

        anom_node = self._anomaly_node_id(anomaly, idx)
        severity = anomaly.get("severity", "unknown").lower()

        self.G.add_node(
            anom_node,
            node_type="anomaly",
            label=f"{anomaly.get('type', 'anomaly')} [{severity}]",
            anomaly_type=anomaly.get("type", "unknown"),
            severity=severity,
            detail=anomaly.get("detail", ""),
            timestamp=anomaly.get("timestamp", ""),
            weight=SEVERITY_WEIGHT.get(severity, 1),
            **NODE_TYPES["anomaly"],
        )

        self.G.add_edge(
            anom_node, svc_node,
            relation="DETECTED_IN",
            weight=SEVERITY_WEIGHT.get(severity, 1),
        )

        # Bump anomaly counter on the service node
        self.G.nodes[svc_node]["anomaly_count"] = (
            self.G.nodes[svc_node].get("anomaly_count", 0) + 1
        )

        return anom_node

    def add_dependency_edges(self, edges: list[dict]):
        """
        Add service-to-service call edges from knowledge_graph_edges output.
        Each edge: { "source": str, "target": str, "relation": str }
        """
        call_counts: dict[tuple, int] = defaultdict(int)
        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            if src and tgt:
                call_counts[(src, tgt)] += 1

        for (src, tgt), count in call_counts.items():
            src_node = self.add_service(src)
            tgt_node = self.add_service(tgt)
            self.G.add_edge(
                src_node, tgt_node,
                relation="CALLS",
                weight=count,
                call_count=count,
            )

    def mark_root_cause(self, root_service: str):
        """Highlight the root-cause service with a special edge from incident node."""
        svc_node = self._service_node_id(root_service)
        if self.G.has_node(svc_node):
            self.G.nodes[svc_node]["is_root_cause"] = True
            self.G.nodes[svc_node]["color"] = "#8E44AD"  # purple
            if not self.G.has_edge(self.incident_id, svc_node):
                self.G.add_edge(self.incident_id, svc_node, relation="ROOT_CAUSE", weight=5)
            else:
                self.G[self.incident_id][svc_node]["relation"] = "ROOT_CAUSE"

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_blast_radius(self) -> list[dict]:
        """
        Return services sorted by impact score.
        Impact = anomaly_count * severity_weight + in-degree (dependencies).
        """
        scores = []
        for node_id, attrs in self.G.nodes(data=True):
            if attrs.get("node_type") != "service":
                continue
            in_deg = self.G.in_degree(node_id)
            out_deg = self.G.out_degree(node_id)
            anom_count = attrs.get("anomaly_count", 0)
            impact = anom_count * 3 + in_deg + out_deg
            scores.append({
                "service": attrs.get("service_name", node_id),
                "impact_score": impact,
                "anomaly_count": anom_count,
                "dependency_in": in_deg,
                "dependency_out": out_deg,
                "is_root_cause": attrs.get("is_root_cause", False),
            })
        return sorted(scores, key=lambda x: x["impact_score"], reverse=True)

    def get_critical_path(self) -> list[str]:
        """
        Return the longest path in the DAG as the critical dependency chain.
        Falls back to empty list if graph has cycles.
        """
        try:
            dag = nx.DiGraph(
                (u, v) for u, v, d in self.G.edges(data=True)
                if d.get("relation") == "CALLS"
            )
            if nx.is_directed_acyclic_graph(dag) and dag.nodes:
                path = nx.dag_longest_path(dag)
                return [
                    self.G.nodes[n].get("service_name", n)
                    for n in path
                    if self.G.nodes.get(n, {}).get("node_type") == "service"
                ]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize graph to JSON-safe dict (for API response)."""
        nodes = []
        for node_id, attrs in self.G.nodes(data=True):
            nodes.append({"id": node_id, **{k: v for k, v in attrs.items()}})

        edges = []
        for src, tgt, attrs in self.G.edges(data=True):
            edges.append({"source": src, "target": tgt, **attrs})

        return {
            "incident_id": self.incident_id,
            "node_count": self.G.number_of_nodes(),
            "edge_count": self.G.number_of_edges(),
            "nodes": nodes,
            "edges": edges,
            "blast_radius": self.get_blast_radius(),
            "critical_path": self.get_critical_path(),
        }

    def to_mermaid(self) -> str:
        """Export graph as a Mermaid flowchart (for README/docs embedding)."""
        lines = ["graph TD"]
        style_lines = []

        for node_id, attrs in self.G.nodes(data=True):
            safe_id = node_id.replace(":", "_").replace("-", "_")
            label = attrs.get("label", node_id)
            ntype = attrs.get("node_type", "service")

            if ntype == "incident":
                lines.append(f'    {safe_id}["{label}"]')
                style_lines.append(f"    style {safe_id} fill:#F39C12,color:#fff")
            elif ntype == "service":
                shape = "((" if attrs.get("is_root_cause") else "("
                close = "))" if attrs.get("is_root_cause") else ")"
                lines.append(f'    {safe_id}{shape}"{label}"{close}')
                color = "#8E44AD" if attrs.get("is_root_cause") else "#4A90D9"
                style_lines.append(f"    style {safe_id} fill:{color},color:#fff")
            elif ntype == "anomaly":
                lines.append(f'    {safe_id}{{"{label}"}}')
                style_lines.append(f"    style {safe_id} fill:#E74C3C,color:#fff")

        for src, tgt, attrs in self.G.edges(data=True):
            safe_src = src.replace(":", "_").replace("-", "_")
            safe_tgt = tgt.replace(":", "_").replace("-", "_")
            relation = attrs.get("relation", "")
            lines.append(f"    {safe_src} -->|{relation}| {safe_tgt}")

        return "\n".join(lines + style_lines)

    def to_dot(self) -> str:
        """Export graph as Graphviz DOT format."""
        lines = [f'digraph "{self.incident_id}" {{', "    rankdir=LR;"]
        for node_id, attrs in self.G.nodes(data=True):
            label = attrs.get("label", node_id).replace('"', "'")
            color = attrs.get("color", "#cccccc")
            shape = attrs.get("shape", "ellipse")
            safe_id = f'"{node_id}"'
            lines.append(
                f'    {safe_id} [label="{label}", shape={shape}, '
                f'style=filled, fillcolor="{color}", fontcolor="white"];'
            )
        for src, tgt, attrs in self.G.edges(data=True):
            relation = attrs.get("relation", "")
            weight = attrs.get("weight", 1)
            lines.append(
                f'    "{src}" -> "{tgt}" [label="{relation}", penwidth={min(weight, 5)}];'
            )
        lines.append("}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory — build from agent output
# ---------------------------------------------------------------------------

def build_graph_from_investigation(result: dict) -> IncidentKnowledgeGraph:
    """
    Build a complete IncidentKnowledgeGraph from the agent's finalized state dict.

    Args:
        result: dict with keys:
            incident_id, anomalies, affected_services, causal_chain,
            knowledge_graph_edges, root_cause

    Returns:
        Populated IncidentKnowledgeGraph instance
    """
    g = IncidentKnowledgeGraph(result.get("incident_id", "INC-UNKNOWN"))

    # Add all affected services
    for svc in result.get("affected_services", []):
        g.add_service(svc)

    # Add anomalies
    for idx, anomaly in enumerate(result.get("anomalies", [])):
        g.add_anomaly(anomaly, idx)

    # Add dependency edges from log co-occurrence
    g.add_dependency_edges(result.get("knowledge_graph_edges", []))

    # Mark root cause service (heuristic: first service in causal chain)
    causal_chain = result.get("causal_chain", [])
    if causal_chain:
        g.mark_root_cause(causal_chain[0])

    logger.info(
        f"[build_graph] {g.G.number_of_nodes()} nodes, "
        f"{g.G.number_of_edges()} edges for {g.incident_id}"
    )
    return g