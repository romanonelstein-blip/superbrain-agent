from __future__ import annotations

from dataclasses import dataclass
from .models import Evidence


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    reason: str


class Verifier:
    def verify(self, evidence: tuple[Evidence, ...], unresolved_conflict: bool) -> VerificationResult:
        if unresolved_conflict:
            return VerificationResult(False, "unresolved material conflict")
        if not evidence:
            return VerificationResult(False, "no evidence")
        if any(not e.verified for e in evidence):
            return VerificationResult(False, "unverified evidence remains")
        return VerificationResult(True, "evidence verified")
