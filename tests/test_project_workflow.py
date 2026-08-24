"""Configuration, scaffolding, reports, and command-line workflow tests."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

import alphaverdict.demo as demo_module
from alphaverdict import __version__
from alphaverdict.audit.models import AuditReport, Verdict
from alphaverdict.cli import app
from alphaverdict.config.reader import load_project
from alphaverdict.engine.screen import screen
from alphaverdict.exceptions import ConfigurationError
from alphaverdict.report.render import (
    artifact_fingerprint,
    write_run_report,
    write_screen_result,
)
from alphaverdict.scaffold import initialize_project


def _project_file(root: Path, prices: str = "prices.csv") -> Path:
    config = root / "alphaverdict.yml"
    config.write_text(
        f"""version: 1
data:
  adapter: csv
  options:
    prices: {prices}
    metadata:
      price_adjustment: split_adjusted
      survivorship: unknown
strategy: strategy.py:Strategy
request:
  kinds: [prices]
screen:
  top_n: 4
backtest:
  rebalance: monthly
  top_k: 2
  max_weight: 0.5
audit:
  bootstrap_simulations: 100
  permutation_simulations: 100
output_dir: evidence
""",
        encoding="utf-8",
    )
    return config


def test_scaffold_creates_reviewable_project_and_refuses_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    created = initialize_project(destination)
    assert len(created) == 4
    assert (destination / "alphaverdict.yml").is_file()
    assert "buy" not in (destination / "strategy.py").read_text(encoding="utf-8").lower()
    with pytest.raises(ConfigurationError, match="overwrite"):
        initialize_project(destination)
    assert len(initialize_project(destination, force=True)) == 4


def test_package_versions_cannot_drift() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__


def test_config_loads_strict_runtime(demo_bundle, tmp_path: Path) -> None:
    initialize_project(tmp_path, force=True)
    demo_bundle.prices.to_csv(tmp_path / "prices.csv", index=False)
    config = _project_file(tmp_path)
    project = load_project(config)
    assert project.output_path == (tmp_path / "evidence").resolve()
    assert project.requested_kinds == ("prices",)
    assert project.make_adapter().load(project.request).prices.shape == demo_bundle.prices.shape
    assert project.make_strategy().name == "my-stock-strategy"
    assert project.make_engine().config.top_k == 2


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("version: 2\ndata: {}\nstrategy: x:y\n", "version 1"),
        ("version: 1\nunknown: true\ndata: {}\nstrategy: x:y\n", "unknown root"),
        ("version: 1\ndata: {}\nstrategy: x:y\n", "data.adapter"),
        ("version: 1\ndata: {adapter: csv}\n", "strategy is required"),
        ("version: 1\ndata: []\nstrategy: x:y\n", "data must"),
        ("version: 1\ndata: {adapter: csv}\nstrategy: x:y\nscreen: {top_n: 0}\n", "invalid screen"),
        (
            "version: 1\ndata: {adapter: csv}\nstrategy: x:y\nallow_outside_root: 'false'\n",
            "true or false",
        ),
    ],
)
def test_config_rejects_unknown_or_invalid_input(
    tmp_path: Path, content: str, message: str
) -> None:
    path = tmp_path / "bad.yml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_project(path)
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_project(tmp_path / "missing.yml")


def test_report_artifacts_are_self_contained_and_hash_bound(
    demo_result,
    tmp_path: Path,
) -> None:
    audit = AuditReport(Verdict.WARN, 74, (), (), ("Validate on untouched data.",), "No promise.")
    artifacts = write_run_report(demo_result, audit, tmp_path)
    assert artifacts.report.is_file()
    html = artifacts.report.read_text(encoding="utf-8")
    assert "AlphaVerdict" in html and "<svg" in html
    assert "<script src=" not in html and "<link href=" not in html
    manifest = json.loads(artifacts.manifest.read_text(encoding="utf-8"))
    assert set(manifest["artifacts"]) == {"result.json", "audit.json", "report.html"}
    assert len(artifact_fingerprint(artifacts)) == 64
    first_manifest = artifacts.manifest.read_bytes()
    repeated = write_run_report(demo_result, audit, tmp_path)
    assert repeated.directory == artifacts.directory
    assert repeated.manifest.read_bytes() == first_manifest


def test_screen_json_writer(demo_bundle, demo_strategy, tmp_path: Path) -> None:
    result = screen(demo_bundle, demo_strategy, top_n=3)
    target = write_screen_result(result, tmp_path / "nested" / "screen.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ranked"][0]["rank"] == 1


def test_cli_version_init_validate_and_screen(demo_bundle, tmp_path: Path) -> None:
    runner = CliRunner()
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0 and "AlphaVerdict" in version.output
    project = tmp_path / "cli-project"
    initialized = runner.invoke(app, ["init", str(project)])
    assert initialized.exit_code == 0
    demo_bundle.prices.to_csv(project / "prices.csv", index=False)
    config = _project_file(project)
    validated = runner.invoke(app, ["validate", "--config", str(config)])
    assert validated.exit_code == 0 and "Configuration valid" in validated.output
    output = project / "screen.json"
    screened = runner.invoke(
        app,
        ["screen", "--config", str(config), "--output", str(output)],
    )
    assert screened.exit_code == 0 and output.is_file()
    researched = runner.invoke(app, ["backtest", "--config", str(config)])
    assert researched.exit_code == 0 and "Verdict" in researched.output
    assert list((project / "evidence").glob("*/report.html"))
    failed = runner.invoke(app, ["validate", "--config", str(project / "missing.yml")])
    assert failed.exit_code == 2 and "Error" in failed.output


def test_cli_demo_uses_synthetic_warning(monkeypatch, tmp_path: Path) -> None:
    original = demo_module.synthetic_bundle
    monkeypatch.setattr(
        demo_module,
        "synthetic_bundle",
        lambda seed, sessions=520: original(seed=seed, sessions=130),
    )
    result = CliRunner().invoke(app, ["demo", "--output", str(tmp_path), "--seed", "5"])
    assert result.exit_code == 0
    assert "Synthetic demo only" in result.output
    assert list(tmp_path.glob("*/report.html"))
