"""
AegisAI FastAPI Application
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

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
    description="Autonomous Production Incident Investigator — LangGraph + Claude.",
    version="0.2.0",
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
        "version": "0.2.0",
        "description": "Autonomous Production Incident Investigator",
        "docs": "/docs",
    }


@app.get("/health", tags=["Meta"])
def health():
    return {"status": "ok"}


@app.post("/investigate", response_model=InvestigateResponse, tags=["Investigation"])
def investigate(
    request: InvestigateRequest,
    report_format: str = Query(default="none", enum=["none", "markdown", "json", "both"]),
):
    """
    Run autonomous root cause analysis on logs and metrics.

    Pipeline: detect_anomalies → correlate_dependencies → reason_root_cause → finalize_report

    Optional ?report_format=markdown|json|both returns a generated report in the response.
    """
    from src.agent.graph import investigation_graph
    from src.graph.knowledge_graph import build_graph_from_investigation
    from src.reporter.report import generate_report

    if not request.logs and not request.metrics:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'logs' or 'metrics' must be provided.",
        )

    logger.info(f"Starting investigation: {request.incident_id}")

    initial_state = {
        "incident_id": request.incident_id,
        "logs":    [l.model_dump() for l in request.logs],
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
        logger.exception(f"Investigation failed: {request.incident_id}")
        raise HTTPException(status_code=500, detail=f"Investigation failed: {str(e)}")

    # Build knowledge graph
    graph = build_graph_from_investigation(result)
    graph_data = graph.to_dict()

    # Optionally generate report
    report_out: dict = {}
    if report_format != "none":
        report_out = generate_report(result, graph, fmt=report_format)

    logger.info(
        f"Investigation complete: {request.incident_id} "
        f"| confidence={result['confidence']:.0%} "
        f"| nodes={graph_data['node_count']}"
    )

    response = InvestigateResponse(
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

    # Attach graph + report as extra fields
    response_dict = response.model_dump()
    response_dict["graph"] = graph_data
    if report_out:
        response_dict["report"] = report_out

    return response_dict


@app.get("/investigate/{incident_id}/report", tags=["Investigation"])
def get_report_markdown(incident_id: str):
    """
    Placeholder — in a stateful deployment this would fetch a stored report.
    Returns usage instructions for now.
    """
    return PlainTextResponse(
        content=(
            f"# Report for {incident_id}\n\n"
            "To generate a report, POST to /investigate with "
            "?report_format=markdown|json|both\n"
        ),
        media_type="text/markdown",
    )