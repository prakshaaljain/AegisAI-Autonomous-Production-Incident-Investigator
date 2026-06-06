"""
AegisAI API Models
Pydantic schemas for request validation and response serialization.
"""

from typing import Optional
from pydantic import BaseModel, Field
import uuid


class LogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    service: str
    trace_id: Optional[str] = None
    metadata: Optional[dict] = None


class MetricEntry(BaseModel):
    timestamp: str
    name: str
    value: float
    service: str
    unit: Optional[str] = None


class InvestigateRequest(BaseModel):
    incident_id: Optional[str] = Field(
        default_factory=lambda: f"INC-{uuid.uuid4().hex[:8].upper()}"
    )
    logs: list[LogEntry] = []
    metrics: list[MetricEntry] = []


class TimelineEvent(BaseModel):
    timestamp: str
    event: str
    service: str
    severity: str


class InvestigateResponse(BaseModel):
    incident_id: str
    root_cause: str
    confidence: float
    affected_services: list[str]
    anomalies: list[dict]
    causal_chain: list[str]
    timeline: list[dict]
    remediation: list[str]
    summary: str
    knowledge_graph_edges: list[dict]