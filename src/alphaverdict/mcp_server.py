"""Dependency-free Model Context Protocol server exposing AlphaVerdict verdicts.

AlphaVerdict speaks the MCP stdio transport (newline-delimited JSON-RPC 2.0) with
zero additional dependencies, so any agent runtime can call deterministic research
verdicts without trusting a model inside the loop. The server never reads raw
credentials and never mutates anything outside the configured project directories.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, ClassVar

from alphaverdict._version import __version__
from alphaverdict.agents.council import AuditCouncil
from alphaverdict.audit.models import AuditConfig, AuditReport
from alphaverdict.config.reader import load_project
from alphaverdict.data.contracts import DataRequest
from alphaverdict.data.reference import RealMomentumStrategy, YFinanceBundleAdapter
from alphaverdict.demo import DemoEvidenceStrategy, synthetic_bundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, RebalanceFrequency
from alphaverdict.engine.screen import screen as run_screen
from alphaverdict.exceptions import AlphaVerdictError, SecurityBoundaryError
from alphaverdict.report.render import write_run_report

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "alphaverdict"
MAX_LINE_BYTES = 1_048_576
ROOT_ENV = "ALPHAVERDICT_MCP_ROOT"
DEBUG_ENV = "ALPHAVERDICT_MCP_DEBUG"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class FindingKnowledge:
    """Static remediation knowledge for every stable finding code."""

    CODES: ClassVar[dict[str, dict[str, str]]] = {
        "DATA_PRICE_INVARIANT": {
            "severity": "critical",
            "summary": "Price rows violate market invariants (impossible OHLC or volume).",
            "remediation": "Repair the adapter mapping and rerun the complete pipeline.",
        },
        "DATA_TEMPORAL_LEAK": {
            "severity": "critical",
            "summary": "Features are marked knowable before they were observed.",
            "remediation": (
                "Correct availability timestamps; fiscal periods and publication dates "
                "are not interchangeable."
            ),
        },
        "DATA_ADJUSTMENT_UNKNOWN": {
            "severity": "high",
            "summary": "The bundle does not declare its split/dividend adjustment policy.",
            "remediation": "Set metadata.price_adjustment and verify corporate actions.",
        },
        "DATA_SURVIVORSHIP_UNKNOWN": {
            "severity": "high",
            "summary": "Point-in-time universe membership is not proven.",
            "remediation": (
                "Supply effective_from/effective_to membership rows including delistings."
            ),
        },
        "DATA_COVERAGE_UNEVEN": {
            "severity": "medium",
            "summary": "History coverage varies sharply across symbols.",
            "remediation": "Explain listing gaps; never silently fill missing sessions.",
        },
        "DATA_SYNTHETIC": {
            "severity": "info",
            "summary": "Run uses demonstration data; it validates plumbing only.",
            "remediation": "Rerun with licensed or user-owned real point-in-time data.",
        },
        "STRATEGY_NONDETERMINISTIC": {
            "severity": "critical",
            "summary": "Repeated evaluation of an identical snapshot changed results.",
            "remediation": "Seed or remove randomness and external state.",
        },
        "CAUSALITY_PREFIX_CHANGED": {
            "severity": "critical",
            "summary": "Past signals changed when future data was corrupted.",
            "remediation": "Remove full-sample transforms, backward fills, and future-dependent state.",
        },
        "CAUSALITY_UNTESTED": {
            "severity": "high",
            "summary": "Sample too short for prefix-invariance testing.",
            "remediation": "Provide longer history before accepting causality claims.",
        },
        "FOLD_INSTABILITY": {
            "severity": "high",
            "summary": "Most contiguous evaluation folds were unprofitable.",
            "remediation": "Simplify the rule and pre-declare a fresh holdout.",
        },
        "BOOTSTRAP_UNCERTAIN": {
            "severity": "medium",
            "summary": "Block-bootstrap evidence is not decisive.",
            "remediation": "Collect more independent periods and inspect the lower path.",
        },
        "COST_FRAGILE": {
            "severity": "high",
            "summary": "Plausible friction erases the result.",
            "remediation": "Reduce turnover or require a wider pre-cost edge.",
        },
        "BENCHMARK_MISSING": {
            "severity": "medium",
            "summary": "No point-in-time benchmark series was supplied.",
            "remediation": ("Configure a benchmark symbol present in user-owned prices."),
        },
        "REGIME_INSTABILITY": {
            "severity": "medium",
            "summary": "Performance concentrates in one coarse benchmark regime.",
            "remediation": "Treat regime dependence as a hypothesis needing fresh data.",
        },
        "TRIALS_LEDGER_MISSING": {
            "severity": "medium",
            "summary": "No research diary records what was attempted.",
            "remediation": (
                "Enable the automatic trial ledger; undeclared searches overstate confidence."
            ),
        },
        "TRIALS_UNDERDECLARED": {
            "severity": "high",
            "summary": "Recorded search exceeds the declared n_trials burden.",
            "remediation": (
                "Raise audit.n_trials to the recorded variant count and recheck deflated Sharpe."
            ),
        },
        "TRIALS_LEDGER_TAMPERED": {
            "severity": "critical",
            "summary": "Trial ledger hash chain failed verification.",
            "remediation": (
                "Restore from backup or restart with a written note; do not trust dependent verdicts."
            ),
        },
        "PERFORMANCE_SAMPLE_SMALL": {
            "severity": "medium",
            "summary": "Too few rebalance periods support the performance summary.",
            "remediation": "Extend the date range or shorten the rebalance interval.",
        },
        "PERFORMANCE_EXTREME_SHARPE": {
            "severity": "high",
            "summary": "Extreme Sharpe often accompanies leakage or understated friction.",
            "remediation": "Audit timestamps, adjustments, stale prices, and search burden.",
        },
        "SYMBOL_CONCENTRATION": {
            "severity": "medium",
            "summary": "A few symbols dominate absolute contribution.",
            "remediation": "Re-evaluate without those symbols; inspect universe breadth.",
        },
        "BENCHMARK_UNDERPERFORMANCE": {
            "severity": "low",
            "summary": "Strategy underperformed its configured benchmark.",
            "remediation": "Justify complexity with risk or diversification evidence.",
        },
        "TRACK_RECORD_SHORT": {
            "severity": "high",
            "summary": "Track record is shorter than the statistical evidence threshold.",
            "remediation": "Extend untouched out-of-sample history before concluding.",
        },
        "MULTIPLE_TESTING": {
            "severity": "high",
            "summary": "Result does not clear its declared search burden (deflated Sharpe).",
            "remediation": "Record all attempted variants; preserve a fresh final holdout.",
        },
        "MEAN_NOT_SIGNIFICANT": {
            "severity": "medium",
            "summary": "Mean return is indistinguishable from a sign-flipped null.",
            "remediation": "Treat the edge as unproven; gather more observations.",
        },
        "RETURN_CONCENTRATION": {
            "severity": "high",
            "summary": "A few periods dominate absolute returns.",
            "remediation": "Repeat analysis without dominant periods; trace holdings.",
        },
    }


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        **({"required": required} if required else {}),
    }


def tool_definitions() -> list[dict[str, Any]]:
    """Return the advertised MCP tool descriptors."""
    return [
        {
            "name": "run_demo_verdict",
            "description": (
                "Run the full AlphaVerdict pipeline on clearly labelled synthetic data and "
                "return the adversarial council verdict with findings."
            ),
            "inputSchema": _schema({"fast": {"type": "boolean", "default": False}}),
        },
        {
            "name": "run_project_verdict",
            "description": (
                "Backtest and audit one AlphaVerdict project directory "
                "(must contain alphaverdict.yml) and return the merged verdict."
            ),
            "inputSchema": _schema(
                {
                    "project_path": {"type": "string"},
                    "fast": {"type": "boolean", "default": False},
                },
                required=["project_path"],
            ),
        },
        {
            "name": "run_screen",
            "description": (
                "Rank one AlphaVerdict project's universe at a point in time and return "
                "the top-ranked symbols with scores."
            ),
            "inputSchema": _schema(
                {
                    "project_path": {"type": "string"},
                    "as_of": {"type": "string", "description": "Optional decision date."},
                },
                required=["project_path"],
            ),
        },
        {
            "name": "explain_finding",
            "description": "Explain one AlphaVerdict finding code and its remediation.",
            "inputSchema": _schema({"code": {"type": "string"}}, required=["code"]),
        },
        {
            "name": "list_findings",
            "description": "List every stable finding code the audit council can emit.",
            "inputSchema": _schema({}),
        },
    ]


def fast_audit_config(seed: int = 7) -> AuditConfig:
    """Return a reduced but valid audit configuration for interactive tool calls."""
    return AuditConfig(
        bootstrap_simulations=100,
        permutation_simulations=100,
        cost_multipliers=(0.0, 1.0, 2.0),
        causality_cutoffs=2,
        stability_folds=2,
        seed=seed,
    )


def run_demo_verdict(*, fast: bool = False) -> dict[str, Any]:
    """Execute the synthetic demo end to end and summarize the verdict."""
    bundle = synthetic_bundle(seed=7)
    strategy = DemoEvidenceStrategy(momentum_sessions=63)
    config = BacktestConfig(
        rebalance=RebalanceFrequency.WEEKLY,
        top_k=3,
        max_weight=0.40,
        benchmark_symbol="DEMO-BENCH",
        seed=7,
    )
    engine = BacktestEngine(config)
    result = engine.run(bundle, strategy)
    audit = AuditCouncil().review(
        bundle,
        strategy,
        engine,
        result,
        fast_audit_config() if fast else None,
    )
    return _audit_summary(audit, result.manifest.get("run_id"), strategy.name)


def run_project_verdict(project_path: str, *, fast: bool = False) -> dict[str, Any]:
    """Backtest and audit one trusted local project directory."""
    project = load_project(_confined_config_path(project_path))
    bundle = project.make_adapter().load(project.request)
    strategy = project.make_strategy()
    engine = project.make_engine()
    result = engine.run(bundle, strategy)
    audit = AuditCouncil().review(
        bundle,
        strategy,
        engine,
        result,
        fast_audit_config(result.config.seed) if fast else project.audit,
    )
    artifacts = write_run_report(result, audit, project.output_path)
    summary = _audit_summary(audit, result.manifest.get("run_id"), strategy.name)
    summary["report_path"] = str(artifacts.report)
    return summary


def run_project_screen(project_path: str, as_of: str | None = None) -> dict[str, Any]:
    """Rank one trusted project's universe at a point in time."""
    project = load_project(_confined_config_path(project_path))
    bundle = project.make_adapter().load(project.request)
    result = run_screen(
        bundle,
        project.make_strategy(),
        as_of=as_of,
        top_n=project.screen.top_n,
        minimum_score=project.screen.minimum_score,
    )
    return {
        "strategy": result.strategy_name,
        "as_of": result.as_of.isoformat(),
        "ranked": result.ranked.head(20).to_dict(orient="records"),
    }


def _confined_config_path(project_path: str) -> Path:
    root_value = os.environ.get(ROOT_ENV, "").strip()
    resolved = Path(project_path).expanduser().resolve()
    if root_value:
        root = Path(root_value).expanduser().resolve()
        if resolved != root and root not in resolved.parents:
            raise SecurityBoundaryError(f"project path escapes {ROOT_ENV}: {project_path}")
    return resolved / "alphaverdict.yml"


def run_reference_verdict(*, fast: bool = False) -> dict[str, Any]:
    """Run the bundled Yahoo Finance reference demo when the optional extra is installed."""
    adapter = YFinanceBundleAdapter()
    strategy = RealMomentumStrategy(benchmark_symbol=adapter.benchmark)
    config = BacktestConfig(
        rebalance=RebalanceFrequency.WEEKLY,
        top_k=5,
        max_weight=0.20,
        benchmark_symbol=adapter.benchmark,
        seed=7,
    )
    engine = BacktestEngine(config)
    bundle = adapter.load(DataRequest())
    result = engine.run(bundle, strategy)
    audit = AuditCouncil().review(
        bundle,
        strategy,
        engine,
        result,
        fast_audit_config() if fast else None,
    )
    return _audit_summary(audit, result.manifest.get("run_id"), strategy.name)


def _audit_summary(audit: AuditReport, run_id: Any, strategy_name: str) -> dict[str, Any]:
    return {
        "strategy": strategy_name,
        "run_id": str(run_id) if run_id is not None else None,
        "verdict": audit.verdict.value,
        "score": audit.score,
        "caveat": audit.caveat,
        "findings": [
            {
                "code": finding.code,
                "severity": finding.severity.label,
                "title": finding.title,
                "recommendation": finding.recommendation,
            }
            for finding in audit.findings[:10]
        ],
        "recommendations": list(audit.recommendations)[:6],
    }


def _text_response(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": False,
    }


def _error_response(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "run_demo_verdict":
        payload = run_demo_verdict(fast=bool(arguments.get("fast", False)))
    elif name == "run_project_verdict":
        path_value = arguments.get("project_path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise TypeError("project_path must be a non-empty string")
        payload = run_project_verdict(path_value, fast=bool(arguments.get("fast", False)))
    elif name == "run_screen":
        path_value = arguments.get("project_path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise TypeError("project_path must be a non-empty string")
        as_of_value = arguments.get("as_of")
        as_of = as_of_value if isinstance(as_of_value, str) and as_of_value.strip() else None
        payload = run_project_screen(path_value, as_of)
    elif name == "explain_finding":
        code_value = arguments.get("code")
        if not isinstance(code_value, str):
            raise ValueError("code must be a string")
        entry = FindingKnowledge.CODES.get(code_value.strip().upper())
        if entry is None:
            return _error_response(f"unknown finding code: {code_value}")
        payload = {"code": code_value.strip().upper(), **entry}
    elif name == "list_findings":
        payload = {
            "codes": [
                {"code": code, "severity": meta["severity"], "summary": meta["summary"]}
                for code, meta in sorted(FindingKnowledge.CODES.items())
            ]
        }
    else:
        return _error_response(f"unknown tool: {name}")
    return _text_response(payload)


def negotiate_version(requested: Any) -> str:
    """Pick the newest mutually supported protocol version."""
    if isinstance(requested, str) and requested in SUPPORTED_VERSIONS:
        return requested
    return PROTOCOL_VERSION


def _initialize_result(params: Any) -> dict[str, Any]:
    version = negotiate_version(params.get("protocolVersion") if isinstance(params, dict) else None)
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
        "instructions": (
            "Deterministic stock-research verdicts only. Every tool returns "
            "evidence-backed findings; none of them place orders or promise returns."
        ),
    }


def _tools_call_params(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    params = payload.get("params")
    if not isinstance(params, dict):
        raise TypeError("params must be an object")
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str):
        raise TypeError("tool name must be a string")
    if not isinstance(arguments, dict):
        raise TypeError("tool arguments must be an object")
    return name, arguments


def handle_message(payload: Any) -> dict[str, Any] | None:
    """Route one decoded JSON-RPC object; notifications return None."""
    if isinstance(payload, list):
        return _failure(None, INVALID_REQUEST, "batch requests are not supported")
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return _failure(None, INVALID_REQUEST, "request must be a JSON object")
    method = payload.get("method")
    request_id = payload.get("id")
    is_notification = "id" not in payload
    if not isinstance(method, str):
        return None if is_notification else _failure(request_id, INVALID_REQUEST, "method required")

    def respond(result: dict[str, Any]) -> dict[str, Any] | None:
        return None if is_notification else {"jsonrpc": "2.0", "id": request_id, "result": result}

    try:
        if method == "initialize":
            return respond(_initialize_result(payload.get("params")))
        if method == "ping":
            return respond({})
        if method == "tools/list":
            return respond({"tools": tool_definitions()})
        if method == "tools/call":
            name, arguments = _tools_call_params(payload)
            return respond(_dispatch_tool(name, arguments))
        if method.startswith("notifications/"):
            return None
        if is_notification:
            return None
        return _failure(request_id, METHOD_NOT_FOUND, method)
    except AlphaVerdictError as exc:
        return respond(_error_response(str(exc)))
    except Exception as exc:  # noqa: BLE001 - JSON-RPC requires internal errors to surface
        return respond(_error_response(f"internal error: {exc}"))


def _failure(request_id: Any, code: int, message: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": str(message)},
    }


def handle_line(line: str) -> str | None:
    """Parse, route, and serialize one newline-delimited request."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        response: dict[str, Any] | None = _failure(None, PARSE_ERROR, f"parse error: {exc.msg}")
    else:
        response = handle_message(payload)
    if response is None:
        return None
    return json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _debug(message: str) -> None:
    if os.environ.get(DEBUG_ENV, "").strip() not in {"", "0", "false"}:
        sys.stderr.write(f"{SERVER_NAME}-mcp[debug]: {message}\n")


def serve(reader: Any = None, writer: Any = None) -> int:
    """Serve MCP over stdio until EOF; returns a process exit code."""
    source = reader if reader is not None else sys.stdin
    target = writer if writer is not None else sys.stdout
    sys.stderr.write(f"{SERVER_NAME}-mcp {__version__}: serving deterministic tools on stdio\n")
    for raw_line in source:
        line = raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8")
        response: str | None
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            response = json.dumps(
                _failure(None, INVALID_REQUEST, f"request exceeds {MAX_LINE_BYTES} bytes"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        else:
            _debug(f"<- {line.strip()[:200]}")
            response = handle_line(line)
            if response is not None:
                _debug(f"-> {response[:200]}")
        if response is not None:
            target.write(response + "\n")
            target.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
