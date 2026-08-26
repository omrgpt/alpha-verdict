"""AlphaVerdict command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from alphaverdict._version import __version__
from alphaverdict.agents.council import AuditCouncil
from alphaverdict.audit.ledger import TrialLedger
from alphaverdict.audit.models import AuditReport
from alphaverdict.config.models import ProjectConfig
from alphaverdict.config.reader import load_project
from alphaverdict.data.bundle import DataBundle
from alphaverdict.demo import DemoOutcome, run_corrupted_demo, run_real_demo, run_synthetic_demo
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestResult
from alphaverdict.engine.screen import screen as run_screen
from alphaverdict.engine.walkforward import WalkForwardConfig, walk_forward
from alphaverdict.exceptions import AlphaVerdictError
from alphaverdict.mcp_server import serve as serve_mcp
from alphaverdict.report.render import RunArtifacts, write_run_report, write_screen_result
from alphaverdict.scaffold import initialize_project
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.utils import _json_safe

app = typer.Typer(
    name="alphaverdict",
    no_args_is_help=True,
    help="Point-in-time screening and adversarial research for user-owned stock data.",
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"AlphaVerdict {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Research infrastructure only: no brokers, orders, or trade execution."""


def _fail(exc: Exception) -> None:
    console.print(f"[bold red]Error:[/bold red] {exc}")
    raise typer.Exit(code=2) from exc


@app.command()
def init(
    destination: Annotated[
        Path, typer.Argument(help="New or existing project directory.")
    ] = Path(),
    force: Annotated[
        bool, typer.Option(help="Overwrite only AlphaVerdict scaffold files.")
    ] = False,
) -> None:
    """Scaffold a provider-neutral stock research project."""
    try:
        created = initialize_project(destination, force=force)
    except (AlphaVerdictError, OSError) as exc:
        _fail(exc)
    console.print(
        f"[bold green]Created {len(created)} files[/bold green] in {destination.resolve()}"
    )
    console.print("Review strategy.py and alphaverdict.yml before running trusted local code.")


@app.command()
def validate(
    config: Annotated[Path, typer.Option("--config", "-c", help="Project YAML.")] = Path(
        "alphaverdict.yml"
    ),
) -> None:
    """Validate configuration, adapter health, and canonical data contracts."""
    try:
        project = load_project(config)
        adapter = project.make_adapter()
        health = adapter.health()
        bundle = adapter.load(project.request)
        strategy = project.make_strategy()
    except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
        _fail(exc)
    console.print(f"[bold green]Configuration valid[/bold green] | adapter={health.status.value}")
    console.print(f"strategy={strategy.name} | data={json.dumps(_json_safe(bundle.describe()))}")


@app.command("screen")
def screen_command(
    config: Annotated[Path, typer.Option("--config", "-c", help="Project YAML.")] = Path(
        "alphaverdict.yml"
    ),
    as_of: Annotated[str | None, typer.Option(help="UTC-compatible decision date.")] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Optional JSON artifact.")
    ] = None,
) -> None:
    """Rank the stock universe at one point in time; never place orders."""
    try:
        project = load_project(config)
        bundle = project.make_adapter().load(project.request)
        result = run_screen(
            bundle,
            project.make_strategy(),
            as_of=as_of,
            top_n=project.screen.top_n,
            minimum_score=project.screen.minimum_score,
        )
    except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
        _fail(exc)
    table = Table(title=f"{result.strategy_name} | {result.as_of.date()}")
    for column in ("rank", "symbol", "score", "eligible", "rationale"):
        table.add_column(column)
    for row in result.ranked.itertuples(index=False):
        table.add_row(
            str(row.rank),
            str(row.symbol),
            f"{row.score:.6f}",
            str(row.eligible),
            str(row.rationale),
        )
    console.print(table)
    if output is not None:
        path = write_screen_result(result, output)
        console.print(f"Saved {path}")


@app.command()
def backtest(
    config: Annotated[Path, typer.Option("--config", "-c", help="Project YAML.")] = Path(
        "alphaverdict.yml"
    ),
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit a machine-readable verdict summary.")
    ] = False,
    no_ledger: Annotated[
        bool, typer.Option("--no-ledger", help="Skip appending this run to trials.jsonl.")
    ] = False,
) -> None:
    """Run causal research, the audit council, and a portable evidence report."""
    try:
        project = load_project(config)
        bundle = project.make_adapter().load(project.request)
        strategy = project.make_strategy()
        engine = project.make_engine()
        result = engine.run(bundle, strategy)
        audit = _review_with_ledger(project, bundle, strategy, engine, result, no_ledger)
        artifacts = write_run_report(result, audit, project.output_path)
    except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
        _fail(exc)
    if as_json:
        console.print_json(
            json.dumps(
                _json_safe(_verdict_summary(audit, strategy, result, artifacts)), default=str
            )
        )
        return
    _print_human_verdict(audit)
    console.print(f"Report: {artifacts.report}")


def _review_with_ledger(
    project: ProjectConfig,
    bundle: DataBundle,
    strategy: StockStrategy,
    engine: BacktestEngine,
    result: BacktestResult,
    no_ledger: bool,
) -> AuditReport:
    if no_ledger:
        return AuditCouncil().review(bundle, strategy, engine, result, project.audit)
    ledger = TrialLedger(project.root / "trials.jsonl")
    ledger.record_result(result)
    return AuditCouncil(trials_ledger_path=str(ledger.path)).review(
        bundle, strategy, engine, result, project.audit
    )


def _verdict_summary(
    audit: AuditReport,
    strategy: StockStrategy,
    result: BacktestResult,
    artifacts: RunArtifacts,
) -> dict[str, Any]:
    return {
        "verdict": audit.verdict.value,
        "score": audit.score,
        "strategy": strategy.name,
        "run_id": result.manifest.get("run_id"),
        "report_path": str(artifacts.report),
        "diagnoses": [experiment.to_dict() for experiment in audit.diagnoses],
        "strengths": list(audit.strengths),
        "findings": [
            {"code": finding.code, "severity": finding.severity.label} for finding in audit.findings
        ],
    }


def _print_human_verdict(audit: AuditReport) -> None:
    console.print(
        f"[bold]Verdict {audit.verdict.value.upper()} | evidence score {audit.score}/100[/bold]"
    )
    if audit.strengths:
        console.print("[bold green]What held up[/bold green]")
        for strength in audit.strengths:
            console.print(f"  [green]+[/green] {strength}")
    if audit.diagnoses:
        table = Table(title="Diagnosed next experiments for THIS strategy", show_lines=False)
        for column in ("#", "diagnosis", "evidence from your run", "run this"):
            table.add_column(column, overflow="fold")
        for experiment in audit.diagnoses[:5]:
            table.add_row(
                str(experiment.rank),
                f"[bold]{experiment.title}[/bold]\n{experiment.rationale}",
                experiment.observation,
                experiment.experiment,
            )
        console.print(table)
    else:
        console.print(
            "[dim]No strategy-specific experiments triggered; "
            "process recommendations below still apply.[/dim]"
        )
    table = Table(title="Audit findings", show_lines=False)
    for column in ("severity", "code", "finding"):
        table.add_column(column)
    for finding in audit.findings[:10]:
        table.add_row(finding.severity.label.upper(), finding.code, finding.title)
    if not audit.findings:
        table.add_row("-", "-", "no findings; this run survived every configured reviewer")
    console.print(table)


@app.command("walkforward")
def walkforward_command(
    config: Annotated[Path, typer.Option("--config", "-c", help="Project YAML.")] = Path(
        "alphaverdict.yml"
    ),
    train: Annotated[int, typer.Option(help="Training rebalance periods per fold.")] = 52,
    test: Annotated[int, typer.Option("--test", help="Out-of-sample periods per fold.")] = 13,
    embargo: Annotated[int, typer.Option(help="Embargo periods between train and test.")] = 2,
) -> None:
    """Evaluate the strategy across embargoed contiguous walk-forward folds."""
    try:
        project = load_project(config)
        bundle = project.make_adapter().load(project.request)
        strategy = project.make_strategy()
        settings = WalkForwardConfig(
            train_periods=train, test_periods=test, embargo_periods=embargo
        )
        result = walk_forward(bundle, strategy, project.make_engine(), settings)
        output_dir = project.output_path
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / "walkforward.json"
        artifact.write_text(json.dumps(_json_safe(result.to_dict()), indent=2) + "\n")
    except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
        _fail(exc)
    console.print(
        f"[bold]Walk-forward: {len(result.folds)} folds | hint {result.verdict_hint.upper()}[/bold]"
    )
    table = Table(title="Fold evidence")
    for column in ("fold", "train return", "test return", "test sharpe", "test drawdown"):
        table.add_column(column)
    for fold in result.folds:
        table.add_row(
            str(fold.index),
            f"{fold.train_total_return:.2%}",
            f"{fold.test_total_return:.2%}",
            f"{fold.test_sharpe:.3f}",
            f"{fold.test_max_drawdown:.2%}",
        )
    console.print(table)
    if result.degradation_ratio is not None:
        console.print(f"OOS/IS Sharpe retention: {result.degradation_ratio:.0%}")
    for warning in result.warnings:
        console.print(f"[yellow]{warning}[/yellow]")
    console.print(f"Artifact: {artifact}")


@app.command()
def demo(
    output: Annotated[Path, typer.Option("--output", "-o", help="Artifact directory.")] = Path(
        "demo-runs"
    ),
    seed: Annotated[int, typer.Option(help="Deterministic fixture seed.")] = 7,
    real: Annotated[
        bool,
        typer.Option(
            "--real",
            help="Use public Yahoo Finance daily data instead of the synthetic fixture.",
        ),
    ] = False,
    period: Annotated[
        str | None,
        typer.Option(help="[real] Download window: 1y, 5y, max, ..."),
    ] = None,
    top_k: Annotated[
        int | None, typer.Option("--top-k", help="[real] Portfolio breadth per rebalance.")
    ] = None,
    benchmark: Annotated[str | None, typer.Option(help="[real] Benchmark symbol.")] = None,
    symbols: Annotated[
        str | None,
        typer.Option(help="[real] Comma-separated watchlist overriding the default universe."),
    ] = None,
    show_catch: Annotated[
        bool,
        typer.Option(
            "--show-catch",
            help="Also run a deliberately corrupted twin so you can watch the council catch the lie.",
        ),
    ] = False,
) -> None:
    """Exercise every layer: synthetic plumbing demo or public-data reference run."""
    parsed_symbols: tuple[str, ...] | None = None
    if symbols is not None:
        parsed_symbols = tuple(item.strip().upper() for item in symbols.split(",") if item.strip())
        if not parsed_symbols:
            _fail(ValueError("--symbols must contain at least one ticker"))
            return
    try:
        outcome = _run_demo(output, seed, real, period, top_k, benchmark, parsed_symbols)
    except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
        _fail(exc)
    _print_verdict_card(outcome)
    _print_diagnoses(outcome.audit)
    if show_catch and not real:
        try:
            corrupted = run_corrupted_demo(output, seed=seed)
        except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
            _fail(exc)
        _print_catch_theater(outcome, corrupted, output)
    console.print(f"Report: {outcome.artifacts.report}")


def _run_demo(
    output: Path,
    seed: int,
    real: bool,
    period: str | None,
    top_k: int | None,
    benchmark: str | None,
    parsed_symbols: tuple[str, ...] | None,
) -> DemoOutcome:
    if real:
        options: dict[str, Any] = {}
        if period is not None:
            options["period"] = period
        if top_k is not None:
            options["top_k"] = top_k
        if benchmark is not None:
            options["benchmark"] = benchmark
        if parsed_symbols is not None:
            options["symbols"] = parsed_symbols
        outcome = run_real_demo(output, seed=seed, **options)
        console.print(
            "[bold yellow]Public snapshot on a current-listing universe; "
            "survivorship limits apply. Not investment advice.[/bold yellow]"
        )
        return outcome
    outcome = run_synthetic_demo(output, seed=seed)
    console.print(
        "[bold yellow]Synthetic demo only - this is not evidence of a market edge.[/bold yellow]"
    )
    return outcome


def _print_verdict_card(outcome: DemoOutcome) -> None:
    console.print(
        f"[bold]{outcome.audit.verdict.value.upper()} | "
        f"evidence score {outcome.audit.score}/100[/bold]"
    )
    timings = outcome.result.manifest.get("timings") or {}
    if timings:
        console.print(
            f"backtest {timings.get('backtest_seconds', '-')}s · "
            f"audit {timings.get('audit_seconds', '-')}s"
        )


def _print_diagnoses(audit: AuditReport, limit: int = 3) -> None:
    if not audit.diagnoses:
        return
    table = Table(title="Diagnosed next experiments", show_lines=False)
    for column in ("#", "diagnosis", "evidence", "run this"):
        table.add_column(column, overflow="fold")
    for item in audit.diagnoses[:limit]:
        table.add_row(str(item.rank), item.title, item.observation, item.experiment)
    console.print(table)


def _print_catch_theater(honest: DemoOutcome, corrupted: DemoOutcome, output: Path) -> None:
    caught_codes = sorted({finding.code for finding in corrupted.audit.findings})
    console.print("[bold]--show-catch: same strategy, corrupted data[/bold]")
    console.print(
        "A few fundamentals rows were made knowable 30 days BEFORE they were observed — "
        "a classic research leak."
    )
    console.print(f"Corrupted twin verdict: [bold]{corrupted.audit.verdict.value.upper()}[/bold]")
    console.print(f"Council flagged: {', '.join(caught_codes) or '(nothing - this is a bug)'}")
    for finding in corrupted.audit.findings:
        if finding.code == "DATA_TEMPORAL_LEAK":
            console.print(f"  [red]✗ {finding.code}:[/red] {finding.evidence}")
    console.print(
        f"Honest data → {honest.audit.verdict.value.upper()} · Corrupted data → "
        f"{corrupted.audit.verdict.value.upper()}. Same engine, same code — "
        "the only difference is the lie, and it was caught.\n"
        f"Compare the two reports side by side in {output}/"
    )
    leak_caught = any(code == "DATA_TEMPORAL_LEAK" for code in caught_codes)
    if corrupted.audit.score == honest.audit.score or not leak_caught:
        raise AssertionError("corrupted demo was not caught; self-check failure")


@app.command("mcp")
def mcp_command() -> None:
    """Serve deterministic verdict tools over the Model Context Protocol (stdio)."""
    raise typer.Exit(code=serve_mcp())


ledger_app = typer.Typer(help="Inspect and verify the append-only trial ledger.")
app.add_typer(ledger_app, name="ledger")


@ledger_app.command("show")
def ledger_show(
    path: Annotated[Path, typer.Option("--path", help="Ledger file.")] = Path("trials.jsonl"),
) -> None:
    """Print every chained entry: runs and manual notes."""
    entries = TrialLedger(path).entries()
    if not entries:
        console.print("Ledger is empty or missing; runs append automatically.")
        return
    table = Table(title=f"{len(entries)} ledger entries | {path}")
    for column in ("#", "time", "kind", "strategy", "label"):
        table.add_column(column)
    for item in entries:
        table.add_row(
            str(item.index),
            item.timestamp,
            item.kind,
            item.strategy_name or "-",
            item.label or "-",
        )
    console.print(table)
    intact, bad_index = TrialLedger(path).verify()
    console.print(
        "[bold green]Hash chain intact[/bold green]"
        if intact
        else f"[bold red]Chain broken at entry {bad_index}[/bold red]"
    )


@ledger_app.command("verify")
def ledger_verify(
    path: Annotated[Path, typer.Option("--path", help="Ledger file.")] = Path("trials.jsonl"),
) -> None:
    """Recompute the hash chain and report the first broken entry."""
    intact, bad_index = TrialLedger(path).verify()
    if intact:
        count = len(TrialLedger(path).entries())
        console.print(f"[bold green]Intact[/bold green] — {count} entries verified.")
    else:
        console.print(f"[bold red]TAMPERED[/bold red] — chain breaks at entry {bad_index}.")
        raise typer.Exit(code=1)


@ledger_app.command("note")
def ledger_note(
    label: Annotated[str, typer.Argument(help="Milestone description.")],
    path: Annotated[Path, typer.Option("--path", help="Ledger file.")] = Path("trials.jsonl"),
) -> None:
    """Append a manual milestone (hypothesis change, parameter freeze, holdout declaration)."""
    entry = TrialLedger(path).record_note(label)
    console.print(f"Noted as entry #{entry.index} · hash {entry.entry_hash[:12]}…")


@app.command()
def selfcheck() -> None:
    """Run the adversarial bias zoo: prove the council catches every planted trap."""
    from alphaverdict.selfcheck.zoo import run_self_check  # noqa: PLC0415 - keeps CLI import light

    failures = run_self_check(console.print)
    if failures:
        console.print(f"[bold red]SELF-CHECK FAILED:[/bold red] {len(failures)} case(s):")
        for name in failures:
            console.print(f"  - {name}")
        raise typer.Exit(code=1)
    console.print("[bold green]All adversarial cases detected.[/bold green]")
