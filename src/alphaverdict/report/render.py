"""Self-contained, deterministic HTML and JSON report rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from jinja2 import Environment, PackageLoader, select_autoescape

from alphaverdict.audit.models import AuditReport
from alphaverdict.engine.models import BacktestResult, ScreenResult
from alphaverdict.utils import _json_safe, canonical_json, sha256_file, sha256_text


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    directory: Path
    report: Path
    result: Path
    audit: Path
    manifest: Path


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _format_metric(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if not isinstance(value, (int, float)):
        return str(value)
    if not np.isfinite(float(value)):
        return "—"
    percentage_metrics = {
        "total_return",
        "annual_return",
        "annual_volatility",
        "max_drawdown",
        "win_rate",
        "best_period",
        "worst_period",
        "var_95",
        "cvar_95",
        "annual_alpha",
        "average_turnover",
        "average_gross_exposure",
    }
    if key in percentage_metrics:
        return f"{float(value):.2%}"
    if key == "periods":
        return f"{int(value):,}"
    if key == "annual_turnover":
        return f"{float(value):.2f}x"
    return f"{float(value):,.3f}"


def _equity_svg(equity: pd.DataFrame, width: int = 900, height: int = 260) -> str:
    if equity.empty:
        return ""
    values = equity.astype(float).replace([np.inf, -np.inf], np.nan).ffill().bfill()
    finite = values.to_numpy()[np.isfinite(values.to_numpy())]
    if not len(finite):
        return ""
    low, high = float(finite.min()), float(finite.max())
    span = max(high - low, 1e-12)
    count = max(len(values) - 1, 1)
    colors = {"strategy": "#5eead4", "benchmark": "#94a3b8"}
    paths: list[str] = []
    for column in values:
        points: list[str] = []
        for index, value in enumerate(values[column]):
            if not np.isfinite(value):
                continue
            x = 12 + index / count * (width - 24)
            y = 12 + (high - float(value)) / span * (height - 24)
            points.append(f"{x:.1f},{y:.1f}")
        if points:
            color = colors.get(str(column), "#fbbf24")
            paths.append(
                f'<polyline points="{escape(" ".join(points))}" fill="none" '
                f'stroke="{color}" stroke-width="2" vector-effect="non-scaling-stroke" />'
            )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Equity curves" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<rect width="100%" height="100%" rx="12" fill="#0b1220" />' + "".join(paths) + "</svg>"
    )


def write_run_report(
    result: BacktestResult,
    audit: AuditReport,
    output_root: Path,
) -> RunArtifacts:
    """Write one immutable run directory identified by its manifest run ID."""
    run_id = str(result.manifest["run_id"])
    directory = output_root.expanduser().resolve() / run_id
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "result.json"
    audit_path = directory / "audit.json"
    report_path = directory / "report.html"
    manifest_path = directory / "manifest.json"
    _write_json(result_path, result.to_dict())
    _write_json(audit_path, audit.to_dict())

    environment = Environment(
        loader=PackageLoader("alphaverdict", "templates"),
        autoescape=select_autoescape(("html", "xml")),
        enable_async=False,
    )
    template = environment.get_template("report.html.j2")
    report_path.write_text(
        template.render(
            run_id=run_id,
            generated_at=pd.Timestamp(result.returns.index.max()).isoformat(),
            result=result,
            audit=audit,
            metrics=[
                (key.replace("_", " ").title(), _format_metric(key, value))
                for key, value in result.metrics.items()
            ],
            equity_svg=_equity_svg(result.equity),
        ),
        encoding="utf-8",
    )
    manifest = {
        **result.manifest,
        "artifact_schema_version": "1",
        "artifacts": {
            item.name: sha256_file(item) for item in (result_path, audit_path, report_path)
        },
    }
    _write_json(manifest_path, manifest)
    return RunArtifacts(directory, report_path, result_path, audit_path, manifest_path)


def write_screen_result(result: ScreenResult, output: Path) -> Path:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, result.to_dict())
    return output


def artifact_fingerprint(artifacts: RunArtifacts) -> str:
    """Return a stable digest over the machine-readable artifact manifest."""
    content = canonical_json(json.loads(artifacts.manifest.read_text(encoding="utf-8")))
    return sha256_text(content)
