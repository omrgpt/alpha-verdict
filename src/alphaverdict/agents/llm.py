"""Opt-in narrative extension with a deliberately narrow evidence boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from alphaverdict.audit.models import AuditReport
from alphaverdict.utils import canonical_json


@dataclass(frozen=True, slots=True)
class BoundedNarrativeReviewer:
    """Send only the merged audit JSON to a user-supplied text model callable.

    Raw prices, news payloads, strategy source, credentials, and filesystem paths
    are intentionally outside this interface. AlphaVerdict never enables it by
    default and never chooses a provider for the user.
    """

    invoke: Callable[[str], str]
    maximum_characters: int = 8_000

    def summarize(self, report: AuditReport) -> str:
        evidence = canonical_json(report.to_dict())
        prompt = (
            "Summarize this stock-strategy research audit without adding facts, predictions, trade instructions, "
            "targets, or claims of future profitability. Prioritize critical findings and next validation steps.\n"
            + evidence
        )
        result = str(self.invoke(prompt)).strip()
        if not result:
            raise ValueError("narrative reviewer returned empty text")
        return result[: self.maximum_characters]
