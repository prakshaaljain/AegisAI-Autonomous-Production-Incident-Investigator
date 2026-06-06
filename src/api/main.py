"""
AegisAI FastAPI Application
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.models.schemas import InvestigateRequest, InvestigateResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AegisAI starting up...")
    from src.agent.graph import investigation_graph  # noqa: F401
    logger.info("Investigation graph compiled and ready.")
    yield
    logger.info("AegisAI shutting down.")


app = FastAPI(
    title="AegisAI",
    description="Autonomous Production Incident Investigator powered by LangGraph + Claude.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Meta"])
def root():
    return {
        "name": "AegisAI",
        "version": "0.1.0",
        "description": "Autonomous Production Incident Investigator",
        "docs": "/docs",
    }


@app.get("/health", tags=["Meta"])
def health():
    return {"status": "ok"}


@app.post("/investigate", response_model=InvestigateResponse, tags=["Investigation"])
def investigate(request: InvestigateRequest):
    """
    Run autonomous root cause analysis on logs and metrics.

    Pipeline: detect_anomalies → correlate_dependencies → reason_root_cause → finalize_report
    """
    from src.agent.graph import investigation_graph

    if not request.logs and not request.metrics:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'logs' or 'metrics' must be provided.",
        )

    logger.info(f"Starting investigation: {request.incident_id}")

    initial_state = {
        "incident_id": request.incident_id,
        "logs": [l.model_dump() for l in request.logs],
        "metrics": [m.model_dump() for m in request.metrics],
        "anomalies": [],
        "affected_services": [],
        "causal_chain": [],
        "knowledge_graph_edges": [],
        "messages": [],
        "root_cause": "",
        "confidence": 0.0,
        "timeline": [],
        "remediation": [],
        "summary": "",
    }

    try:
        result = investigation_graph.invoke(initial_state)
    except EnvironmentError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"Investigation failed for {request.incident_id}")
        raise HTTPException(status_code=500, detail=f"Investigation failed: {str(e)}")

    logger.info(f"Investigation complete: {request.incident_id} | confidence={result['confidence']}")

    return InvestigateResponse(
        incident_id=request.incident_id,
        root_cause=result["root_cause"],
        confidence=result["confidence"],
        affected_services=result["affected_services"],
        anomalies=result["anomalies"],
        causal_chain=result["causal_chain"],
        timeline=result["timeline"],
        remediation=result["remediation"],
        summary=result["summary"],
        knowledge_graph_edges=result["knowledge_graph_edges"],
    )