from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from .models import Evidence, Stance


@dataclass(frozen=True)
class DissentResult:
    passed: bool
    counterevidence: tuple[Evidence, ...]
    reason: str


class BlindedDissent:
    """
    The callback receives only the question and usable evidence, not the
    Grand Council's provisional conclusion. This preserves blindness.
    """

    def evaluate(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
        search_fn: Callable[[str, tuple[Evidence, ...]], tuple[Evidence, ...]] | None = None,
    ) -> DissentResult:
        if search_fn is None:
            # In prototype mode, absence of a dissent provider cannot validate a YES.
            return DissentResult(False, (), "no blinded dissent provider")

        counter = tuple(search_fn(question, evidence))
        strong = [
            e for e in counter
            if e.stance == Stance.CHALLENGE
            and e.verified
            and (e.reliability * e.freshness * e.relevance) >= 0.55
        ]
        if strong:
            return DissentResult(False, tuple(counter), "material counterevidence found")
        return DissentResult(True, tuple(counter), "no material counterevidence found")
