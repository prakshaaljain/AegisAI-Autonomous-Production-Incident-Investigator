"""
AegisAI Incident Reporter
Generates structured incident reports in Markdown and JSON formats
from a completed investigation result + knowledge graph.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.graph.knowledge_graph import IncidentKnowledgeGraph

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity badge helpers
# ---------------------------------------------------------------------------

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🟢",
    "unknown":  "⚪",
}

CONFIDENCE_LABEL = {
    (0.8, 1.01):  "High ✅",
    (0.5, 0.8):   "Medium ⚠️",
    (0.0, 0.5):   "Low ❌",
}


def _confidence_label(score: float) -> str:
    for (lo, hi), label in CONFIDENCE_LABEL.items():
        if lo <= score < hi:
            return label
    return "Unknown"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Markdown Report
# ---------------------------------------------------------------------------

def generate_markdown(result: dict, graph: IncidentKnowledgeGraph) -> str:
    """
    Generate a full Markdown incident report.

    Args:
        result: Finalized agent state dict
        graph:  Populated IncidentKnowledgeGraph

    Returns:
        Markdown string
    """
    inc_id      = result.get("incident_id", "UNKNOWN")
    root_cause  = result.get("root_cause", "Undetermined")
    confidence  = float(result.get("confidence", 0.0))
    summary     = result.get("summary", "")
    anomalies   = result.get("anomalies", [])
    affected    = result.get("affected_services", [])
    causal      = result.get("causal_chain", [])
    timeline    = result.get("timeline", [])
    remediation = result.get("remediation", [])
    graph_data  = graph.to_dict()
    blast       = graph_data.get("blast_radius", [])

    lines = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines += [
        f"# 🛡️ AegisAI Incident Report",
        f"",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Incident ID** | `{inc_id}` |",
        f"| **Generated** | {_now_utc()} |",
        f"| **Confidence** | {_confidence_label(confidence)} ({confidence:.0%}) |",
        f"| **Affected Services** | {len(affected)} |",
        f"| **Anomalies Detected** | {len(anomalies)} |",
        f"",
    ]

    # ── Executive Summary ────────────────────────────────────────────────────
    lines += [
        f"## 📋 Executive Summary",
        f"",
        f"{summary or '_No summary generated._'}",
        f"",
    ]

    # ── Root Cause ───────────────────────────────────────────────────────────
    lines += [
        f"## 🔍 Root Cause",
        f"",
        f"> {root_cause}",
        f"",
    ]

    # ── Causal Chain ─────────────────────────────────────────────────────────
    if causal:
        lines += [f"## 🔗 Causal Chain", f""]
        for i, svc in enumerate(causal):
            arrow = "→ " if i > 0 else "🚨 "
            lines.append(f"{arrow}`{svc}`")
        lines.append("")

    # ── Blast Radius ─────────────────────────────────────────────────────────
    if blast:
        lines += [
            f"## 💥 Blast Radius",
            f"",
            f"| Service | Impact Score | Anomalies | Dependencies In | Root Cause |",
            f"|---------|-------------|-----------|-----------------|------------|",
        ]
        for b in blast:
            rc_mark = "✅ Yes" if b.get("is_root_cause") else "—"
            lines.append(
                f"| `{b['service']}` | {b['impact_score']} "
                f"| {b['anomaly_count']} | {b['dependency_in']} | {rc_mark} |"
            )
        lines.append("")

    # ── Anomalies ────────────────────────────────────────────────────────────
    if anomalies:
        lines += [f"## ⚠️ Detected Anomalies", f""]
        for a in anomalies:
            sev = a.get("severity", "unknown").lower()
            emoji = SEVERITY_EMOJI.get(sev, "⚪")
            lines += [
                f"### {emoji} {a.get('type', 'anomaly').replace('_', ' ').title()}",
                f"- **Service:** `{a.get('service', 'unknown')}`",
                f"- **Severity:** {sev.capitalize()}",
                f"- **Detail:** {a.get('detail', '—')}",
                f"- **Detected at:** {a.get('timestamp', '—')}",
                f"",
            ]

    # ── Timeline ─────────────────────────────────────────────────────────────
    if timeline:
        lines += [
            f"## 📅 Incident Timeline",
            f"",
            f"| Time | Service | Severity | Event |",
            f"|------|---------|----------|-------|",
        ]
        for event in sorted(timeline, key=lambda e: e.get("timestamp", "")):
            sev = event.get("severity", "").lower()
            emoji = SEVERITY_EMOJI.get(sev, "⚪")
            lines.append(
                f"| `{event.get('timestamp', '—')}` "
                f"| `{event.get('service', '—')}` "
                f"| {emoji} {sev.capitalize()} "
                f"| {event.get('event', '—')} |"
            )
        lines.append("")

    # ── Remediation ──────────────────────────────────────────────────────────
    if remediation:
        lines += [f"## 🔧 Remediation Steps", f""]
        for i, step in enumerate(remediation, 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    # ── Knowledge Graph ──────────────────────────────────────────────────────
    lines += [
        f"## 🕸️ Knowledge Graph",
        f"",
        f"```",
        f"Nodes : {graph_data['node_count']}",
        f"Edges : {graph_data['edge_count']}",
        f"```",
        f"",
    ]

    critical_path = graph_data.get("critical_path", [])
    if critical_path:
        lines += [
            f"**Critical Dependency Path:**",
            f"",
            f"`{'` → `'.join(critical_path)}`",
            f"",
        ]

    # ── Mermaid Diagram ──────────────────────────────────────────────────────
    mermaid = graph.to_mermaid()
    if mermaid:
        lines += [
            f"### Service Dependency Diagram",
            f"",
            f"```mermaid",
            mermaid,
            f"```",
            f"",
        ]

    # ── Footer ───────────────────────────────────────────────────────────────
    lines += [
        f"---",
        f"",
        f"_Generated by [AegisAI](https://github.com/prakshaaljain/"
        f"AegisAI-Autonomous-Production-Incident-Investigator) "
        f"— Autonomous Production Incident Investigator_",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON Report
# ---------------------------------------------------------------------------

def generate_json(result: dict, graph: IncidentKnowledgeGraph) -> dict:
    """
    Generate a structured JSON incident report.
    Combines full agent output with graph analytics.
    """
    graph_data = graph.to_dict()

    return {
        "schema_version": "1.0",
        "generated_at": _now_utc(),
        "incident": {
            "id":                result.get("incident_id"),
            "root_cause":        result.get("root_cause"),
            "confidence":        result.get("confidence"),
            "confidence_label":  _confidence_label(float(result.get("confidence", 0))),
            "summary":           result.get("summary"),
            "affected_services": result.get("affected_services", []),
            "causal_chain":      result.get("causal_chain", []),
        },
        "anomalies":   result.get("anomalies", []),
        "timeline":    result.get("timeline", []),
        "remediation": result.get("remediation", []),
        "graph": {
            "node_count":    graph_data["node_count"],
            "edge_count":    graph_data["edge_count"],
            "blast_radius":  graph_data["blast_radius"],
            "critical_path": graph_data["critical_path"],
            "nodes":         graph_data["nodes"],
            "edges":         graph_data["edges"],
            "mermaid":       graph.to_mermaid(),
            "dot":           graph.to_dot(),
        },
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_report(
    result: dict,
    graph: IncidentKnowledgeGraph,
    fmt: str = "both",
) -> dict[str, Any]:
    """
    Generate incident report in requested format.

    Args:
        result: Finalized agent state dict
        graph:  Populated IncidentKnowledgeGraph
        fmt:    'markdown' | 'json' | 'both'

    Returns:
        dict with keys 'markdown' and/or 'json'
    """
    output: dict[str, Any] = {}

    if fmt in ("markdown", "both"):
        output["markdown"] = generate_markdown(result, graph)
        logger.info(f"[reporter] Markdown report generated ({len(output['markdown'])} chars)")

    if fmt in ("json", "both"):
        output["json"] = generate_json(result, graph)
        logger.info(f"[reporter] JSON report generated")

    return output