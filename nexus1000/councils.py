from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from .models import CouncilVerdict


@dataclass
class SpecialistCouncil:
    council_id: str
    specialty: str
    run_fn: Callable[[str], CouncilVerdict]

    def run(self, question: str) -> CouncilVerdict:
        verdict = self.run_fn(question)
        if verdict.council_id != self.council_id:
            raise ValueError("Council returned mismatched council_id")
        return verdict
