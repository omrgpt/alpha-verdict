"""Build and post AlphaVerdict verdict comments on pull requests.

Runs in two modes:
  --print                 build the markdown and print it (local/CI logs)
  --post --pr N           upsert the comment on a pull request via the REST API
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

MARKER = "<!-- alphaverdict-verdict -->"
API_ROOT = "https://api.github.com"
COLORS = {"pass": "brightgreen", "warn": "orange", "fail": "red"}
SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def find_artifacts(output_dir: Path) -> tuple[Path, Path] | None:
    """Locate the newest run's audit.json and manifest.json."""
    if not output_dir.is_dir():
        return None
    candidates: list[tuple[str, Path, Path]] = []
    for manifest in output_dir.glob("*/manifest.json"):
        run_dir = manifest.parent
        audit = run_dir / "audit.json"
        if audit.is_file():
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                run_id = str(payload.get("run_id", ""))
            except (json.JSONDecodeError, OSError):
                run_id = ""
            candidates.append((run_id, audit, manifest))
    if not candidates:
        return None
    _, audit_path, manifest_path = max(candidates, key=lambda item: item[0])
    return audit_path, manifest_path


def badge_url(audit: dict[str, Any]) -> str:
    verdict = str(audit.get("verdict", "fail")).lower()
    color = COLORS.get(verdict, "red")
    message = f"{verdict.upper()}%20{int(audit.get('score', 0))}%2F100"
    return f"https://img.shields.io/badge/alpha_verdict-{message}-{color}?style=flat-square"


def build_markdown(
    audit: dict[str, Any],
    manifest: dict[str, Any],
    *,
    config_path: str = "alphaverdict.yml",
) -> str:
    """Render the deterministic PR verdict comment."""
    verdict = str(audit.get("verdict", "fail")).upper()
    score = int(audit.get("score", 0)) if isinstance(audit.get("score"), int) else 0
    findings = [item for item in audit.get("findings", []) if isinstance(item, dict)]
    findings.sort(key=lambda item: -SEVERITY_ORDER.get(str(item.get("severity", "")), 0))

    lines: list[str] = [MARKER]
    lines.append(f"## ⚖️ AlphaVerdict verdict: **{verdict}** — evidence score {score}/100")
    lines.append("")
    lines.append(f"![verdict]({badge_url(audit)})")
    lines.append("")
    strategy = manifest.get("strategy_name", "unknown strategy")
    run_id = manifest.get("run_id", "unknown-run")
    lines.append(f"Strategy `{strategy}` · run `{run_id}` · config `{config_path}`")
    lines.append("")
    if findings:
        lines.append("| Severity | Finding | Recommendation |")
        lines.append("| --- | --- | --- |")
        for item in findings[:8]:
            severity = str(item.get("severity", "info")).capitalize()
            code = f"`{item.get('code', '?')}` {item.get('title', '')}"
            recommendation = str(item.get("recommendation", "")).replace("\n", " ")
            lines.append(f"| {severity} | {code} | {recommendation} |")
    else:
        lines.append("_No findings — this run survived every configured reviewer._")
    lines.append("")
    recommendations = [item for item in audit.get("recommendations", []) if isinstance(item, str)]
    if recommendations:
        lines.append("**Next tests:**")
        for item in recommendations[:4]:
            lines.append(f"- {item}")
        lines.append("")
    caveat = str(audit.get("caveat", ""))
    if caveat:
        lines.append(f"> {caveat}")
        lines.append("")
    lines.append(
        "_Deterministic reviewers only — no model produced this verdict. "
        "Full artifacts are attached to the workflow run._"
    )
    return "\n".join(lines) + "\n"


def _api(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urlrequest.Request(  # noqa: S310 - https API root only
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urlrequest.urlopen(request, timeout=30) as response:  # noqa: S310 - https API root only
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else None


def post_comment(token: str, repo: str, pr_number: int, body: str) -> str:
    """Create or update the marker-matched PR comment; returns its HTML URL."""
    existing = _api("GET", f"/repos/{repo}/issues/{pr_number}/comments?per_page=100", token)
    target = None
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict) and str(item.get("body", "")).startswith(MARKER):
                target = item
                break
    if target is not None and isinstance(target.get("id"), int):
        updated = _api(
            "PATCH", f"/repos/{repo}/issues/comments/{target['id']}", token, {"body": body}
        )
    else:
        updated = _api("POST", f"/repos/{repo}/issues/{pr_number}/comments", token, {"body": body})
    return str(updated.get("html_url", "")) if isinstance(updated, dict) else ""


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", help="Explicit path to audit.json.")
    parser.add_argument("--manifest", help="Explicit path to manifest.json.")
    parser.add_argument("--output-dir", default="runs", help="Run artifact root to search.")
    parser.add_argument("--config", default="alphaverdict.yml")
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument("--post", action="store_true")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr", type=int, default=None)
    arguments = parser.parse_args(argv)

    artifacts: tuple[Path, Path] | None = None
    if arguments.audit and arguments.manifest:
        artifacts = (Path(arguments.audit), Path(arguments.manifest))
    else:
        located = find_artifacts(Path(arguments.output_dir))
        if located is not None:
            audit_path = located[0]
            artifacts = (audit_path, located[1])

    if artifacts is None:
        if arguments.print_only or not arguments.post:
            sys.stderr.write("no AlphaVerdict artifacts found; nothing to report\n")
            return 1
        raise SystemExit("no AlphaVerdict artifacts found; run `alphaverdict backtest` first")

    audit_payload = load_json(artifacts[0])
    manifest_payload = load_json(artifacts[1])
    markdown = build_markdown(
        audit_payload,
        manifest_payload,
        config_path=arguments.config,
    )

    if arguments.print_only or not arguments.post:
        sys.stdout.write(markdown)
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    repo = arguments.repo.strip()
    pr_number = arguments.pr
    if not token:
        raise SystemExit("GITHUB_TOKEN (or GH_TOKEN) is required to post comments")
    if not repo or pr_number is None:
        raise SystemExit("--repo and --pr are required to post comments")
    try:
        url = post_comment(token, repo, pr_number, markdown)
    except urlerror.HTTPError as exc:
        raise SystemExit(f"GitHub API error: {exc.code} {exc.reason}") from exc
    sys.stderr.write(f"comment posted: {url}\n")
    sys.stdout.write(f"::notice title=AlphaVerdict::Verdict posted: {url}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
