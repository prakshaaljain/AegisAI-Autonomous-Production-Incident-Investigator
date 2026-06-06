"""
AegisAI Agent State
Defines the shared state that flows through the LangGraph investigation pipeline.
"""

from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class IncidentState(TypedDict):
    # Raw inputs
    logs: list[dict]
    metrics: list[dict]
    incident_id: str

    # Intermediate outputs
    anomalies: list[dict]
    affected_services: list[str]
    causal_chain: list[str]
    knowledge_graph_edges: list[dict]

    # LLM conversation history
    messages: Annotated[list, add_messages]

    # Final outputs
    root_cause: str
    confidence: float
    timeline: list[dict]
    remediation: list[str]
    summary: str