"""AlphaVerdict command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from alphaverdict._version import __version__
from alphaverdict.agents.council import AuditCouncil
from alphaverdict.config.reader import load_project
from alphaverdict.demo import run_real_demo, run_synthetic_demo
from alphaverdict.engine.screen import screen as run_screen
from alphaverdict.exceptions import AlphaVerdictError
from alphaverdict.mcp_server import serve as serve_mcp
from alphaverdict.report.render import write_run_report, write_screen_result
from alphaverdict.scaffold import initialize_project
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
) -> None:
    """Run causal research, the audit council, and a portable evidence report."""
    try:
        project = load_project(config)
        bundle = project.make_adapter().load(project.request)
        strategy = project.make_strategy()
        engine = project.make_engine()
        result = engine.run(bundle, strategy)
        audit = AuditCouncil().review(bundle, strategy, engine, result, project.audit)
        artifacts = write_run_report(result, audit, project.output_path)
    except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
        _fail(exc)
    console.print(
        f"[bold]Verdict {audit.verdict.value.upper()} | evidence score {audit.score}/100[/bold]"
    )
    console.print(f"Report: {artifacts.report}")


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
) -> None:
    """Exercise every layer: synthetic plumbing demo or public-data reference run."""
    try:
        if real:
            outcome = run_real_demo(output, seed=seed)
            console.print(
                "[bold yellow]Public snapshot on a current-listing universe; "
                "survivorship limits apply. Not investment advice.[/bold yellow]"
            )
        else:
            outcome = run_synthetic_demo(output, seed=seed)
            console.print(
                "[bold yellow]Synthetic demo only - this is not evidence of a market edge.[/bold yellow]"
            )
    except (AlphaVerdictError, OSError, TypeError, ValueError) as exc:
        _fail(exc)
    console.print(
        f"[bold]{outcome.audit.verdict.value.upper()} | evidence score {outcome.audit.score}/100[/bold]"
    )
    console.print(f"Report: {outcome.artifacts.report}")


@app.command("mcp")
def mcp_command() -> None:
    """Serve deterministic verdict tools over the Model Context Protocol (stdio)."""
    raise typer.Exit(code=serve_mcp())
