"""Tests for the dependency-free Model Context Protocol server."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from alphaverdict.mcp_server import (
    PROTOCOL_VERSION,
    FindingKnowledge,
    handle_line,
    handle_message,
    negotiate_version,
    run_demo_verdict,
    run_project_verdict,
    serve,
    tool_definitions,
)


def _request(method: str, **params: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


def test_initialize_negotiates_supported_version() -> None:
    response = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert response is not None
    result = response["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "alphaverdict"
    assert "tools" in result["capabilities"]
    assert "deterministic" in result["instructions"].lower()


def test_initialize_falls_back_to_latest_unknown_version() -> None:
    response = handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999"}}
    )
    assert response is not None
    assert response["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_ping_returns_empty_result() -> None:
    response = handle_message({"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert response == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_tools_list_advertises_expected_tools() -> None:
    response = handle_message(_request("tools/list"))
    assert response is not None
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {
        "run_demo_verdict",
        "run_project_verdict",
        "explain_finding",
        "list_findings",
    }
    for tool in response["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_tool_definitions_schemas_are_valid_shapes() -> None:
    for tool in tool_definitions():
        schema = tool["inputSchema"]
        assert isinstance(schema.get("properties", {}), dict)
        if "required" in schema:
            for name in schema["required"]:
                assert name in schema["properties"]


def test_explain_finding_known_code() -> None:
    response = handle_message(
        _request("tools/call", name="explain_finding", arguments={"code": "cost_fragile"})
    )
    assert response is not None
    body = response["result"]
    assert body["isError"] is False
    payload = body["structuredContent"]
    assert payload["code"] == "COST_FRAGILE"
    assert payload["severity"] == "high"
    assert "turnover" in payload["remediation"]
    text = json.loads(body["content"][0]["text"])
    assert text["code"] == "COST_FRAGILE"


def test_explain_finding_unknown_code_is_error_result() -> None:
    response = handle_message(
        _request("tools/call", name="explain_finding", arguments={"code": "NOT_REAL"})
    )
    assert response is not None
    body = response["result"]
    assert body["isError"] is True
    assert "unknown finding code" in body["content"][0]["text"]


def test_list_findings_returns_sorted_codes() -> None:
    response = handle_message(_request("tools/call", name="list_findings", arguments={}))
    assert response is not None
    payload = response["result"]["structuredContent"]
    codes = [item["code"] for item in payload["codes"]]
    assert codes == sorted(codes)
    assert "CAUSALITY_PREFIX_CHANGED" in codes
    assert len(codes) == len(FindingKnowledge.CODES)


def test_unknown_tool_is_error_result() -> None:
    response = handle_message(_request("tools/call", name="does_not_exist", arguments={}))
    assert response is not None
    assert response["result"]["isError"] is True


def test_invalid_tool_params_are_error_results() -> None:
    response = handle_message(_request("tools/call", name="run_project_verdict", arguments={}))
    assert response is not None
    assert response["result"]["isError"] is True

    response = handle_message(
        _request("tools/call", name="explain_finding", arguments={"code": 42})
    )
    assert response is not None
    assert response["result"]["isError"] is True


def test_unknown_method_maps_to_method_not_found() -> None:
    response = handle_message({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
    assert response is not None
    assert response["error"]["code"] == -32601


def test_notifications_never_respond() -> None:
    assert handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert handle_message({"jsonrpc": "2.0", "method": "notifications/unknown"}) is None


def test_batch_and_non_object_requests_are_rejected() -> None:
    batch = handle_message([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert batch is not None
    assert batch["error"]["code"] == -32600

    scalar = handle_message("hello")
    assert scalar is not None
    assert scalar["error"]["code"] == -32600

    missing_method = handle_message({"jsonrpc": "2.0", "id": 2})
    assert missing_method is not None
    assert missing_method["error"]["code"] == -32600


def test_parse_error_on_malformed_json() -> None:
    response = handle_line("{not json")
    assert response is not None
    payload = json.loads(response)
    assert payload["error"]["code"] == -32700
    assert payload["id"] is None


def test_blank_lines_produce_no_response() -> None:
    assert handle_line("") is None
    assert handle_line("   \n") is None


def test_handle_line_round_trip() -> None:
    line = handle_line(json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"}))
    assert line is not None
    payload = json.loads(line)
    assert payload == {"jsonrpc": "2.0", "id": 5, "result": {}}


@pytest.mark.slow
def test_run_demo_verdict_end_to_end() -> None:
    summary = run_demo_verdict(fast=True)
    assert summary["verdict"] in {"pass", "warn", "fail"}
    assert isinstance(summary["score"], int)
    assert 0 <= summary["score"] <= 100
    assert summary["strategy"]
    assert isinstance(summary["findings"], list)
    for finding in summary["findings"]:
        assert set(finding) >= {"code", "severity", "title"}
    assert "not evidence of future returns" in summary["caveat"]


def test_run_project_verdict_requires_directory(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="does not exist"):
        run_project_verdict(str(tmp_path / "missing"))


def test_run_project_verdict_requires_config(tmp_path: Path) -> None:
    with pytest.raises(Exception, match=r"alphaverdict\.yml"):
        run_project_verdict(str(tmp_path))


def _write_project(root: Path) -> None:
    """Create a minimal trusted project: CSV adapter plus a tiny momentum strategy."""
    dates = pd.bdate_range("2024-01-01", periods=120)
    rows: list[str] = ["symbol,timestamp,open,high,low,close,volume,source"]
    for symbol, drift in (("AAA", 0.001), ("BBB", -0.0005), ("CCC", 0.0002)):
        values = 50 + pd.RangeIndex(len(dates)).to_numpy(dtype=float) * drift * 100
        for date, close in zip(dates, values, strict=True):
            rows.append(
                f"{symbol},{date.isoformat()},{close - 1:.4f},{close + 1:.4f},"
                f"{close - 2:.4f},{close:.4f},1000,fixture"
            )
    (root / "prices.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    strategy_code = '''
"""Fixture strategy."""
from dataclasses import dataclass
import pandas as pd
from alphaverdict import StockStrategy, ResearchSnapshot

@dataclass
class TinyMomentum(StockStrategy):
    name = "tiny-momentum"
    minimum_history = 20

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        prices = snapshot.price_history(sessions=21)
        matrix = prices.pivot(index="timestamp", columns="symbol", values="close").sort_index()
        scores = matrix.iloc[-1] / matrix.iloc[0] - 1 if len(matrix) > 1 else pd.Series(dtype=float)
        frame = scores.rename("score").rename_axis("symbol").reset_index()
        frame["eligible"] = frame["score"].notna()
        frame["rationale"] = "fixture momentum"
        return frame
'''
    (root / "strategy.py").write_text(strategy_code, encoding="utf-8")

    config = """
version: 1
data:
  adapter: csv
  options:
    prices: prices.csv
strategy: strategy.py:TinyMomentum
backtest:
  rebalance: weekly
  top_k: 2
  max_weight: 0.6
audit:
  bootstrap_simulations: 100
  permutation_simulations: 100
  causality_cutoffs: 2
  stability_folds: 2
"""
    (root / "alphaverdict.yml").write_text(config.strip() + "\n", encoding="utf-8")


@pytest.mark.slow
def test_run_project_verdict_success(tmp_path: Path) -> None:
    _write_project(tmp_path)
    summary = run_project_verdict(str(tmp_path))
    assert summary["verdict"] in {"pass", "warn", "fail"}
    report_path = summary.get("report_path")
    assert report_path and Path(report_path).is_file()


@pytest.mark.slow
def test_tools_call_run_demo_over_stdio() -> None:
    reader = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "run_demo_verdict", "arguments": {"fast": True}},
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
    )
    writer = io.StringIO()
    code = serve(reader, writer)
    assert code == 0
    lines = [item for item in writer.getvalue().splitlines() if item]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["id"] == 1
    assert payload["result"]["structuredContent"]["verdict"] in {"pass", "warn", "fail"}


def test_negotiate_version_matrix() -> None:
    assert negotiate_version("2025-03-26") == "2025-03-26"
    assert negotiate_version(None) != ""
    assert negotiate_version(42) != ""
