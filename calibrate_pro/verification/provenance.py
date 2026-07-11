"""Evidence labels for calibration metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    NOT_MEASURED = "not_measured"
    ESTIMATED = "estimated"
    MEASURED = "measured"
    SIMULATED = "simulated"
    REPLAYED = "replayed"


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    unit: str
    evidence: EvidenceKind
    source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EvidenceKind):
            raise TypeError("evidence must be an EvidenceKind")
        if self.evidence is EvidenceKind.NOT_MEASURED:
            if self.value is not None:
                raise ValueError("not-measured metrics cannot carry a value")
            return
        if self.value is None or not math.isfinite(self.value):
            raise ValueError(f"{self.evidence.value} metrics require a finite value")
        if not self.source or not self.source.strip():
            raise ValueError(f"{self.evidence.value} metrics require an evidence source")

    def display_text(self, decimals: int = 2) -> str:
        if self.value is None:
            return "Not measured"
        label = {
            EvidenceKind.ESTIMATED: "estimated",
            EvidenceKind.SIMULATED: "simulated",
            EvidenceKind.REPLAYED: "replayed",
        }.get(self.evidence)
        suffix = f" ({label})" if label else ""
        return f"{self.value:.{decimals}f} {self.unit}{suffix}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "evidence": self.evidence.value,
            "source": self.source,
        }
