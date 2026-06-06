"""
AegisAI Investigation Graph
Compiles the LangGraph state machine for autonomous incident investigation.

Pipeline:
  START → detect_anomalies → correlate_dependencies → reason_root_cause → finalize_report → END
"""

from langgraph.graph import StateGraph, START, END

from .state import IncidentState
from .nodes import (
    detect_anomalies,
    correlate_dependencies,
    reason_root_cause,
    finalize_report,
)


def build_investigation_graph():
    builder = StateGraph(IncidentState)

    builder.add_node("detect_anomalies", detect_anomalies)
    builder.add_node("correlate_dependencies", correlate_dependencies)
    builder.add_node("reason_root_cause", reason_root_cause)
    builder.add_node("finalize_report", finalize_report)

    builder.add_edge(START, "detect_anomalies")
    builder.add_edge("detect_anomalies", "correlate_dependencies")
    builder.add_edge("correlate_dependencies", "reason_root_cause")
    builder.add_edge("reason_root_cause", "finalize_report")
    builder.add_edge("finalize_report", END)

    return builder.compile()


# Singleton compiled graph — import this in API handlers
investigation_graph = build_investigation_graph()