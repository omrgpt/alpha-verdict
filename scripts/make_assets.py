"""Generate committable README hero assets and example verdict reports.

Runs two deterministic synthetic pipelines (a healthy sample and a deliberately
corrupted sample), renders their self-contained reports, extracts the real audit
outcomes, and writes dark-theme SVG cards plus badge JSON used by the README.

Usage:
  python scripts/make_assets.py [--docs docs]
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from alphaverdict.agents.council import AuditCouncil
from alphaverdict.audit.models import AuditConfig
from alphaverdict.data.bundle import DataBundle
from alphaverdict.demo import DemoEvidenceStrategy, run_synthetic_demo, synthetic_bundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, RebalanceFrequency
from alphaverdict.report.render import write_run_report

VERDICT_COLORS = {
    "pass": "#34d399",
    "warn": "#fbbf24",
    "fail": "#f87171",
}

BADGE_COLORS = {"pass": "brightgreen", "warn": "orange", "fail": "red"}

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "-apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif"

PASS_LABEL = ("Typical research run", "synthetic - 780 sessions - weekly rebalance")
FAIL_LABEL = ("Sabotaged data run", "synthetic - corrupted timestamps - 150 sessions")


def _verdict(audit: dict[str, Any]) -> str:
    return str(audit.get("verdict", "fail")).strip().lower()


def _score(audit: dict[str, Any]) -> int:
    try:
        return max(0, min(100, int(audit.get("score", 0))))
    except (TypeError, ValueError):
        return 0


def _findings(audit: dict[str, Any], limit: int = 4) -> list[dict[str, str]]:
    rows = [item for item in audit.get("findings", []) if isinstance(item, dict)]
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    rows.sort(key=lambda item: -order.get(str(item.get("severity", "")), 0))
    return [
        {
            "code": str(item.get("code", "UNKNOWN")),
            "severity": str(item.get("severity", "info")),
        }
        for item in rows[:limit]
    ]


def _chip(x: float, y: float, code: str, severity: str) -> tuple[str, float]:
    color = VERDICT_COLORS["fail" if severity in {"critical", "high"} else "warn"]
    width = 11 + 6.6 * len(code)
    label = html.escape(code)
    chip = (
        f'<g><rect x="{x:.0f}" y="{y:.0f}" width="{width:.0f}" height="22" rx="11" '
        f'fill="#111c33"/><text x="{x + width / 2:.0f}" y="{y + 15:.0f}" '
        f'font-family="{MONO}" font-size="11" fill="{color}" text-anchor="middle">{label}</text></g>'
    )
    return chip, x + width + 10


def card_svg(title: str, subtitle: str, audit: dict[str, Any]) -> str:
    """Render one verdict summary card as an SVG string."""
    verdict = _verdict(audit)
    score = _score(audit)
    accent = VERDICT_COLORS[verdict]
    bar_width = round(score * 4.4)
    chips: list[str] = []
    x = 32.0
    for item in _findings(audit):
        chip, x = _chip(x, 128, item["code"], item["severity"])
        if x > 500:
            break
        chips.append(chip)
    title_text = html.escape(title)
    subtitle_text = html.escape(subtitle)
    verdict_text = html.escape(verdict.upper())
    findings_note = html.escape(
        f"{len(audit.get('findings', []))} findings" if audit.get("findings") else "no findings"
    )
    return f"""<svg width="520" height="180" viewBox="0 0 520 180" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="AlphaVerdict {verdict_text} card">
  <rect width="520" height="180" rx="16" fill="#0b1220"/>
  <rect x="1" y="1" width="518" height="178" rx="15" fill="none" stroke="#1e293b" stroke-width="2"/>
  <text x="32" y="42" font-family="{SANS}" font-size="17" font-weight="600" fill="#e2e8f0">{title_text}</text>
  <text x="32" y="64" font-family="{MONO}" font-size="12" fill="#64748b">{subtitle_text}</text>
  <rect x="392" y="22" width="96" height="30" rx="15" fill="#111c33" stroke="{accent}" stroke-width="1.5"/>
  <text x="440" y="42" font-family="{MONO}" font-size="14" font-weight="700" fill="{accent}" text-anchor="middle">{verdict_text}</text>
  <text x="488" y="92" font-family="{SANS}" font-size="26" font-weight="700" fill="#e2e8f0" text-anchor="end">{score}<tspan fill="#475569" font-size="16">/100</tspan></text>
  <rect x="32" y="100" width="456" height="8" rx="4" fill="#16233f"/>
  <rect x="32" y="100" width="{bar_width}" height="8" rx="4" fill="{accent}"/>
  {"".join(chips)}
  <text x="32" y="166" font-family="{MONO}" font-size="11" fill="#475569">{findings_note} - deterministic reviewers - not investment advice</text>
</svg>
"""


def hero_svg(pass_audit: dict[str, Any], fail_audit: dict[str, Any]) -> str:
    """Render the README hero banner with both verdict outcomes."""
    pass_card = card_svg(*PASS_LABEL, pass_audit)
    fail_card = card_svg(*FAIL_LABEL, fail_audit)

    def embed(card: str, dx: int, dy: int) -> str:
        inner = card.split("\n", 2)[2].rsplit("</svg>", 1)[0]
        return f'<g transform="translate({dx},{dy})">{inner}</g>'

    return f"""<svg width="1200" height="560" viewBox="0 0 1200 560" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="AlphaVerdict adversarial verdicts">
  <rect width="1200" height="560" rx="20" fill="#060d1a"/>
  <rect x="1" y="1" width="1198" height="558" rx="19" fill="none" stroke="#1e293b" stroke-width="2"/>
  <circle cx="112" cy="118" r="34" fill="#0b1220" stroke="#14b8a6" stroke-width="2.5"/>
  <path d="M96 128 L112 96 L128 128 Z" fill="none" stroke="#5eead4" stroke-width="2.5" stroke-linejoin="round"/>
  <text x="164" y="112" font-family="{SANS}" font-size="40" font-weight="800" fill="#f1f5f9">AlphaVerdict</text>
  <text x="165" y="140" font-family="{SANS}" font-size="18" fill="#5eead4">Adversarial verdicts for stock strategies.</text>
  <text x="66" y="196" font-family="{SANS}" font-size="16" fill="#94a3b8">Five deterministic reviewers try to falsify your backtest</text>
  <text x="66" y="220" font-family="{SANS}" font-size="16" fill="#94a3b8">before the market does: causality, leakage, friction,</text>
  <text x="66" y="244" font-family="{SANS}" font-size="16" fill="#94a3b8">robustness, and multiple-testing burden.</text>
  <rect x="66" y="278" width="330" height="44" rx="10" fill="#0f1c33" stroke="#233252"/>
  <text x="86" y="305" font-family="{MONO}" font-size="15" fill="#67e8f9">$ uvx alphaverdict demo --real</text>
  <text x="66" y="360" font-family="{SANS}" font-size="13" fill="#64748b">Point-in-time data contract - provider-neutral - no broker, no orders, no AI in the loop</text>
  {embed(pass_card, 620, 90)}
  {embed(fail_card, 620, 300)}
</svg>
"""


def healthy_run() -> tuple[dict[str, Any], Path]:
    """Run a deterministic audit on a long synthetic sample; return audit and report."""
    outcome = run_synthetic_demo(sessions=780, seed=7, fast_audit=True)
    return outcome.audit.to_dict(), outcome.artifacts.report


def sabotaged_run() -> tuple[dict[str, Any], Path]:
    """Produce a deterministic FAIL by corrupting fixture timestamps on purpose.

    Feature availability dates are shifted before their observation dates: a
    textbook look-ahead leak that the data-integrity reviewer must catch as a
    critical finding and fail outright.
    """
    bundle = synthetic_bundle(seed=7, sessions=150)
    corrupted = bundle.features.copy()
    corrupted["available_at"] = corrupted["observed_at"] - pd.Timedelta(days=30)
    sabotaged_bundle = DataBundle(
        prices=bundle.prices,
        features=corrupted,
        events=bundle.events,
        universe=bundle.universe,
        metadata={**bundle.metadata, "purpose": "deliberately corrupted demonstration"},
    )
    strategy = DemoEvidenceStrategy(momentum_sessions=30)
    config = BacktestConfig(
        rebalance=RebalanceFrequency.WEEKLY,
        top_k=2,
        max_weight=0.50,
        commission_bps=40.0,
        slippage_bps=60.0,
        benchmark_symbol="DEMO-BENCH",
        seed=7,
    )
    engine = BacktestEngine(config)
    result = engine.run(sabotaged_bundle, strategy)
    audit = AuditCouncil().review(
        sabotaged_bundle,
        strategy,
        engine,
        result,
        AuditConfig(
            bootstrap_simulations=100,
            permutation_simulations=100,
            cost_multipliers=(0.0, 2.0),
            causality_cutoffs=2,
            stability_folds=2,
            minimum_periods=24,
            seed=7,
        ),
    )
    artifacts = write_run_report(result, audit, Path("_asset-runs"))
    return audit.to_dict(), artifacts.report


def write_assets(docs_root: Path) -> list[Path]:
    """Generate every launch asset under the docs tree."""
    assets_dir = docs_root / "assets"
    badge_dir = docs_root / "badge"
    examples_dir = docs_root / "examples"
    for directory in (assets_dir, badge_dir, examples_dir):
        directory.mkdir(parents=True, exist_ok=True)

    healthy, healthy_report = healthy_run()
    sabotaged, sabotaged_report = sabotaged_run()

    written: list[Path] = []
    outputs = {
        assets_dir / "readme-hero.svg": hero_svg(healthy, sabotaged),
        assets_dir / "verdict-pass.svg": card_svg(*PASS_LABEL, healthy),
        assets_dir / "verdict-fail.svg": card_svg(*FAIL_LABEL, sabotaged),
    }
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
        written.append(path)

    for source, name in (
        (healthy_report, "report-pass.html"),
        (sabotaged_report, "report-fail.html"),
    ):
        if Path(source).is_file():
            target = examples_dir / name
            shutil.copyfile(source, target)
            written.append(target)

    verdict = _verdict(healthy)
    badge = {
        "schemaVersion": 1,
        "label": "alpha verdict",
        "message": f"{verdict.upper()} {_score(healthy)}/100",
        "color": BADGE_COLORS.get(verdict, "orange"),
    }
    badge_path = badge_dir / "demo-verdict.json"
    badge_path.write_text(json.dumps(badge, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(badge_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", default="docs", help="Repository docs directory.")
    arguments = parser.parse_args(argv)
    written = write_assets(Path(arguments.docs))
    for path in written:
        sys.stderr.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
