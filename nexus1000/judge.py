from __future__ import annotations

from .models import FinalDecision, GrandCouncilResult
from .dissent import DissentResult
from .verifier import VerificationResult


class FinalJudge:
    def decide(
        self,
        grand: GrandCouncilResult,
        neis_passed: bool,
        dissent: DissentResult,
        verification: VerificationResult,
    ) -> FinalDecision:
        passes = {
            "grand_council": grand.provisional_yes,
            "neis": neis_passed,
            "blinded_dissent": dissent.passed,
            "verifier": verification.passed,
        }
        yes = all(passes.values())
        reasons = []
        if yes:
            reasons.append("all evidence gates passed")
        else:
            for name, passed in passes.items():
                if not passed:
                    reasons.append(f"{name} failed")
        return FinalDecision(
            value="YES" if yes else "NO",
            reasons=tuple(reasons),
            pipeline_passes=passes,
            grand_council=grand,
        )
