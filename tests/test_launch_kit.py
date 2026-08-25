"""Tests for badge generation, hero assets, and PR verdict comments."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import make_assets  # noqa: E402
import make_badge  # noqa: E402
import verdict_comment  # noqa: E402

PASS_AUDIT: dict[str, Any] = {
    "verdict": "pass",
    "score": 93,
    "caveat": "A pass means only that this run survived the configured tests.",
    "findings": [
        {
            "code": "DATA_SYNTHETIC",
            "severity": "info",
            "title": "Run uses demonstration data",
            "recommendation": "Rerun with real data.",
        }
    ],
    "recommendations": ["Repeat on licensed data."],
}
FAIL_AUDIT: dict[str, Any] = {
    "verdict": "fail",
    "score": 34,
    "caveat": "A pass means only that this run survived the configured tests.",
    "findings": [
        {
            "code": "TRACK_RECORD_SHORT",
            "severity": "high",
            "title": "Track record is shorter than the evidence threshold",
            "recommendation": "Extend untouched out-of-sample history.",
        },
        {
            "code": "COST_FRAGILE",
            "severity": "high",
            "title": "Plausible friction erases the result",
            "recommendation": "Reduce turnover.",
        },
    ],
}


def test_badge_message_and_colors() -> None:
    assert make_badge.badge_message(PASS_AUDIT) == "PASS 93/100"
    assert make_badge.badge_color(PASS_AUDIT) == "brightgreen"
    assert make_badge.badge_color(FAIL_AUDIT) == "red"
    assert make_badge.badge_color({"verdict": "warn", "score": "70"}) == "orange"
    assert make_badge.badge_color({}) == "red"


def test_badge_endpoint_json_shape() -> None:
    payload = make_badge.endpoint_json(FAIL_AUDIT)
    assert payload["schemaVersion"] == 1
    assert payload["label"] == "alpha verdict"
    assert payload["message"] == "FAIL 34/100"
    assert payload["color"] == "red"


def test_badge_static_url_encodes_score() -> None:
    url = make_badge.static_url(PASS_AUDIT)
    assert url.startswith("https://img.shields.io/badge/alpha_verdict-PASS_93%2F100")
    assert "brightgreen" in url


def test_make_badge_main_writes_file(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(PASS_AUDIT), encoding="utf-8")
    output = tmp_path / "badge" / "verdict.json"
    code = make_badge.main([str(audit_path), "--out", str(output)])
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["color"] == "brightgreen"


def test_make_badge_main_url_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(FAIL_AUDIT), encoding="utf-8")
    code = make_badge.main([str(audit_path), "--url"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip().startswith("https://img.shields.io/badge/")
    assert "red" in captured.out


def test_make_badge_rejects_invalid_inputs(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        make_badge.load_audit(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("not-json{", encoding="utf-8")
    with pytest.raises(SystemExit):
        make_badge.load_audit(bad)
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text('{"hello": true}', encoding="utf-8")
    with pytest.raises(SystemExit):
        make_badge.load_audit(incomplete)


def test_card_svg_escapes_hostile_text() -> None:
    hostile = {**PASS_AUDIT, "findings": [{"code": "<script>", "severity": "info"}]}
    svg = make_assets.card_svg("Title <b>", "sub & 'quote'", hostile)
    assert "<script>" not in svg
    assert "&lt;b&gt;" in svg
    assert "&amp;" in svg


def test_hero_svg_embeds_both_cards() -> None:
    svg = make_assets.hero_svg(PASS_AUDIT, FAIL_AUDIT)
    assert svg.count("<svg") >= 1
    assert "PASS" in svg and "FAIL" in svg
    assert "translate(620," in svg


@pytest.mark.slow
def test_write_assets_generates_full_launch_kit(tmp_path: Path) -> None:
    written = make_assets.write_assets(tmp_path)
    names = {path.name for path in written}
    assert {"readme-hero.svg", "verdict-pass.svg", "verdict-fail.svg", "demo-verdict.json"} <= names
    hero = (tmp_path / "assets" / "readme-hero.svg").read_text(encoding="utf-8")
    assert "AlphaVerdict" in hero
    badge = json.loads((tmp_path / "badge" / "demo-verdict.json").read_text(encoding="utf-8"))
    assert badge["schemaVersion"] == 1
    assert badge["color"] in {"brightgreen", "orange", "red"}


def test_verdict_comment_markdown_structure() -> None:
    markdown = verdict_comment.build_markdown(
        PASS_AUDIT, {"strategy_name": "demo", "run_id": "abc123"}, config_path="p.yml"
    )
    assert markdown.startswith(verdict_comment.MARKER)
    assert "**PASS**" in markdown and "93/100" in markdown
    assert "`demo`" in markdown and "abc123" in markdown
    assert "| Severity | Finding | Recommendation |" in markdown
    assert "> A pass means only" in markdown
    assert "- Repeat on licensed data." in markdown


def test_verdict_comment_orders_findings_by_severity() -> None:
    markdown = verdict_comment.build_markdown(FAIL_AUDIT, {})
    track_index = markdown.index("TRACK_RECORD_SHORT")
    cost_index = markdown.index("COST_FRAGILE")
    assert track_index < cost_index


def test_find_artifacts_selects_highest_run_id(tmp_path: Path) -> None:
    for run_id, score in (("aaa111", 10), ("bbb222", 20), ("ccc333", 30)):
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        (run_dir / "audit.json").write_text(
            json.dumps({**FAIL_AUDIT, "score": score}), encoding="utf-8"
        )
        (run_dir / "stray.txt").write_text("x", encoding="utf-8")
    located = verdict_comment.find_artifacts(tmp_path)
    assert located is not None
    audit_payload = json.loads(located[0].read_text(encoding="utf-8"))
    assert audit_payload["score"] == 30
    assert located[1].name == "manifest.json"


def test_find_artifacts_missing_directory(tmp_path: Path) -> None:
    assert verdict_comment.find_artifacts(tmp_path / "nope") is None


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def test_post_comment_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
        calls.append((method, path.split("?", maxsplit=1)[0]))
        if method == "GET":
            return []
        return {"html_url": "https://github.com/x/y/issues/1#issuecomment-9"}

    monkeypatch.setattr(verdict_comment, "_api", fake_api)
    url = verdict_comment.post_comment("t", "x/y", 1, verdict_comment.MARKER + "\nbody")
    assert url.endswith("#issuecomment-9")
    assert calls[0] == ("GET", "/repos/x/y/issues/1/comments")
    assert calls[1] == ("POST", "/repos/x/y/issues/1/comments")


def test_post_comment_updates_existing_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = [{"id": 55, "body": verdict_comment.MARKER + "\nold"}]
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
        calls.append((method, path))
        if method == "GET":
            return existing
        return {"html_url": "u"}

    monkeypatch.setattr(verdict_comment, "_api", fake_api)
    verdict_comment.post_comment("t", "x/y", 1, "new body")
    assert calls[-1][0] == "PATCH"
    assert calls[-1][1] == "/repos/x/y/issues/comments/55"


def test_verdict_comment_print_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    audit_path = tmp_path / "audit.json"
    manifest_path = tmp_path / "manifest.json"
    audit_path.write_text(json.dumps(PASS_AUDIT), encoding="utf-8")
    manifest_path.write_text(json.dumps({"strategy_name": "s", "run_id": "r"}), encoding="utf-8")
    code = verdict_comment.main(
        ["--audit", str(audit_path), "--manifest", str(manifest_path), "--print"]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith(verdict_comment.MARKER)


def test_verdict_comment_requires_token_for_posting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_path = tmp_path / "audit.json"
    manifest_path = tmp_path / "manifest.json"
    audit_path.write_text(json.dumps(PASS_AUDIT), encoding="utf-8")
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="GITHUB_TOKEN"):
        verdict_comment.main(
            [
                "--audit",
                str(audit_path),
                "--manifest",
                str(manifest_path),
                "--post",
                "--repo",
                "x/y",
                "--pr",
                "1",
            ]
        )
