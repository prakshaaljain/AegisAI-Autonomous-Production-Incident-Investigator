"""
AegisAI Agent Nodes
Each function is a node in the LangGraph investigation graph.
"""

import os
import json
import logging
from datetime import datetime
from collections import defaultdict

import numpy as np
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .state import IncidentState

logger = logging.getLogger(__name__)


def _get_llm():
    if os.getenv("ANTHROPIC_API_KEY"):
        return ChatAnthropic(model="claude-sonnet-4-20250514", max_tokens=2048, temperature=0.2)
    if os.getenv("OPENAI_API_KEY"):
        return ChatOpenAI(model="gpt-4o-mini", temperature=0.2, max_tokens=2048)
    raise EnvironmentError("No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env")


def detect_anomalies(state: IncidentState) -> dict:
    anomalies = []
    affected = set()

    error_counts: dict[str, int] = defaultdict(int)
    total_counts: dict[str, int] = defaultdict(int)

    for entry in state.get("logs", []):
        svc = entry.get("service", "unknown")
        level = entry.get("level", "").upper()
        total_counts[svc] += 1
        if level in ("ERROR", "CRITICAL", "FATAL"):
            error_counts[svc] += 1

    for svc, errors in error_counts.items():
        total = total_counts[svc]
        error_rate = errors / total if total > 0 else 0
        if error_rate > 0.10 or errors >= 5:
            severity = "critical" if error_rate > 0.30 or errors >= 20 else "high"
            anomalies.append({
                "type": "error_rate_spike",
                "service": svc,
                "severity": severity,
                "detail": f"{errors}/{total} log entries are errors ({error_rate:.1%})",
                "timestamp": datetime.utcnow().isoformat(),
            })
            affected.add(svc)

    metric_series: dict[tuple, list[float]] = defaultdict(list)
    metric_entries: dict[tuple, list[dict]] = defaultdict(list)

    for m in state.get("metrics", []):
        key = (m.get("service", "unknown"), m.get("name", "unknown"))
        metric_series[key].append(float(m.get("value", 0)))
        metric_entries[key].append(m)

    for (svc, name), values in metric_series.items():
        if len(values) < 3:
            continue
        arr = np.array(values)
        mean, std = arr.mean(), arr.std()
        if std == 0:
            continue
        z_scores = (arr - mean) / std
        spike_indices = np.where(np.abs(z_scores) > 2.5)[0]
        if len(spike_indices) > 0:
            worst_idx = spike_indices[np.argmax(np.abs(z_scores[spike_indices]))]
            anomalies.append({
                "type": "metric_spike",
                "service": svc,
                "metric": name,
                "severity": "high" if abs(z_scores[worst_idx]) > 3.5 else "medium",
                "detail": f"{name} = {values[worst_idx]:.2f} (mean={mean:.2f}, z={z_scores[worst_idx]:.1f})",
                "timestamp": metric_entries[(svc, name)][worst_idx].get("timestamp", ""),
            })
            affected.add(svc)

    logger.info(f"[detect_anomalies] Found {len(anomalies)} anomalies across {len(affected)} services")
    return {"anomalies": anomalies, "affected_services": list(affected)}


def correlate_dependencies(state: IncidentState) -> dict:
    edges = []
    affected = set(state.get("affected_services", []))

    for entry in state.get("logs", []):
        msg = entry.get("message", "")
        src = entry.get("service", "")
        for keyword in ["calling", "request to", "downstream", "depends on", "upstream"]:
            if keyword in msg.lower():
                tokens = msg.lower().split(keyword)
                if len(tokens) > 1:
                    target = tokens[1].strip().split()[0].strip(".:,;'\"()")
                    if target and target != src and len(target) > 2:
                        edges.append({"source": src, "target": target, "relation": "calls"})

    seen = set()
    unique_edges = []
    for e in edges:
        key = (e["source"], e["target"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    dep_count: dict[str, int] = defaultdict(int)
    for e in unique_edges:
        if e["target"] in affected:
            dep_count[e["source"]] += 1

    causal_chain = sorted(affected, key=lambda s: dep_count.get(s, 0), reverse=True)
    logger.info(f"[correlate_dependencies] {len(unique_edges)} edges, chain: {causal_chain}")
    return {"knowledge_graph_edges": unique_edges, "causal_chain": causal_chain}


SYSTEM_PROMPT = """You are AegisAI, an expert SRE performing autonomous root cause analysis.

Given anomalies, a causal chain, and error logs, you must:
1. Identify the single most likely root cause
2. Estimate confidence (0.0 to 1.0)
3. Reconstruct the incident timeline
4. Recommend prioritized remediation steps
5. Write a 2-3 sentence incident summary

Respond ONLY with valid JSON:
{
  "root_cause": "<one sentence>",
  "confidence": <float>,
  "timeline": [{"timestamp": "", "event": "", "service": "", "severity": ""}],
  "remediation": ["<step 1>", "<step 2>"],
  "summary": "<2-3 sentences>"
}"""


def reason_root_cause(state: IncidentState) -> dict:
    llm = _get_llm()

    error_logs = [
        e for e in state.get("logs", [])
        if e.get("level", "").upper() in ("ERROR", "CRITICAL", "FATAL")
    ][:20]

    user_content = f"""
## Detected Anomalies
{json.dumps(state.get("anomalies", []), indent=2)}

## Causal Chain
{json.dumps(state.get("causal_chain", []), indent=2)}

## Error Log Sample
{json.dumps(error_logs, indent=2)}

Respond with valid JSON only.
"""

    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_content)]
    logger.info("[reason_root_cause] Calling LLM...")
    response = llm.invoke(messages)
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    try:
        result = json.loads(raw.strip())
    except json.JSONDecodeError:
        result = {
            "root_cause": "Unable to determine root cause — LLM response could not be parsed.",
            "confidence": 0.0,
            "timeline": [],
            "remediation": ["Review raw anomalies manually."],
            "summary": "Investigation incomplete due to LLM parsing error.",
        }

    return {
        "messages": messages + [response],
        "root_cause": result.get("root_cause", ""),
        "confidence": float(result.get("confidence", 0.0)),
        "timeline": result.get("timeline", []),
        "remediation": result.get("remediation", []),
        "summary": result.get("summary", ""),
    }


def finalize_report(state: IncidentState) -> dict:
    return {
        "root_cause": state.get("root_cause") or "Root cause undetermined.",
        "confidence": state.get("confidence", 0.0),
        "timeline": state.get("timeline") or [],
        "remediation": state.get("remediation") or ["No remediation steps generated."],
        "summary": state.get("summary") or "Investigation complete.",
        "affected_services": state.get("affected_services") or [],
        "anomalies": state.get("anomalies") or [],
    }