"""Generate shields.io badge assets from an AlphaVerdict audit report.

Usage:
  python scripts/make_badge.py runs/<id>/audit.json --out docs/badge/verdict.json
  python scripts/make_badge.py runs/<id>/audit.json --url
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

COLORS = {"pass": "brightgreen", "warn": "orange", "fail": "red"}
LABEL = "alpha verdict"


def load_audit(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise SystemExit(f"audit file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid audit JSON in {source}: {exc}") from exc
    if not isinstance(payload, dict) or "verdict" not in payload or "score" not in payload:
        raise SystemExit(f"{source} is not an AlphaVerdict audit report")
    return payload


def badge_message(audit: dict[str, Any]) -> str:
    verdict = str(audit.get("verdict", "fail")).strip().lower()
    score = audit.get("score", 0)
    try:
        score_value = int(score)
    except (TypeError, ValueError):
        score_value = 0
    return f"{verdict.upper()} {score_value}/100"


def badge_color(audit: dict[str, Any]) -> str:
    return COLORS.get(str(audit.get("verdict", "fail")).strip().lower(), "red")


def endpoint_json(audit: dict[str, Any]) -> dict[str, Any]:
    """Return a shields.io JSON endpoint payload."""
    return {
        "schemaVersion": 1,
        "label": LABEL,
        "message": f"{badge_message(audit)}",
        "color": badge_color(audit),
    }


def static_url(audit: dict[str, Any]) -> str:
    message = quote(badge_message(audit).replace(" ", "_"), safe="")
    return (
        f"https://img.shields.io/badge/{quote(LABEL.replace(' ', '_'), safe='')}"
        f"-{message}-{badge_color(audit)}?style=flat-square"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", help="Path to an audit.json produced by AlphaVerdict.")
    parser.add_argument("--out", help="Output path for the shields endpoint JSON.")
    parser.add_argument(
        "--url", action="store_true", help="Print a static shields URL instead of writing JSON."
    )
    arguments = parser.parse_args(argv)

    audit = load_audit(arguments.audit)
    if arguments.url:
        sys.stdout.write(static_url(audit) + "\n")
        return 0
    if not arguments.out:
        raise SystemExit("either --out or --url is required")
    destination = Path(arguments.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(endpoint_json(audit), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sys.stderr.write(f"wrote {destination}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
