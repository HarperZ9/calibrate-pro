"""A simulated colorimeter that implements the existing InstrumentPort protocol.

The port reads whatever the simulated panel emits now, adds seeded noise, and
spends simulated integration time. Its readings pass the same validation as a
real driver's, through `InstrumentReading`. Its `evidence_kind` is SIMULATED,
and the closed loop labels every metric it reports from this port that way.
"""

from __future__ import annotations

import numpy as np

from calibrate_pro.application.instruments import (
    MINIMUM_TRISTIMULUS,
    InstrumentError,
    InstrumentPort,
    InstrumentReading,
)
from calibrate_pro.calibration.closed_loop.controls import Clock
from calibrate_pro.calibration.closed_loop.sim_panel import SimulatedPanel
from calibrate_pro.verification.provenance import EvidenceKind


class SimulatedInstrument:
    """A noisy simulated colorimeter pointed at one simulated panel."""

    evidence_kind = EvidenceKind.SIMULATED

    def __init__(
        self,
        panel: SimulatedPanel,
        clock: Clock,
        *,
        relative_sigma: float = 0.002,
        absolute_sigma: float = 0.0005,
        integration_s: float = 1.0,
        seed: int = 0,
    ) -> None:
        if relative_sigma < 0.0 or absolute_sigma < 0.0 or integration_s <= 0.0:
            raise ValueError("noise must be non-negative and integration positive")
        self._panel = panel
        self._clock = clock
        self._relative = relative_sigma
        self._absolute = absolute_sigma
        self._integration = integration_s
        self._rng = np.random.default_rng(seed)
        self._identity = f"simulated colorimeter (seed {seed})"
        self._open = True
        self.reads = 0

    def identity(self) -> str:
        return self._identity

    def read(self) -> InstrumentReading:
        if not self._open:
            raise InstrumentError("this instrument session is already closed")
        truth = self._panel.emitted_xyz()
        relative = self._rng.normal(0.0, self._relative, 3) if self._relative else np.zeros(3)
        absolute = self._rng.normal(0.0, self._absolute, 3) if self._absolute else np.zeros(3)
        noisy = np.maximum(truth * (1.0 + relative) + absolute, MINIMUM_TRISTIMULUS)
        self._clock.sleep(self._integration)
        self.reads += 1
        xyz = (float(noisy[0]), float(noisy[1]), float(noisy[2]))
        return InstrumentReading(instrument=self._identity, xyz=xyz, integration_seconds=float(self._integration))

    def close(self) -> None:
        self._open = False


class SimulatedInstrumentSource:
    """An InstrumentSource that opens one simulated instrument."""

    def __init__(self, instrument: SimulatedInstrument) -> None:
        self._instrument = instrument

    def describe(self) -> str:
        return self._instrument.identity()

    def present(self) -> bool:
        return True

    def open(self) -> InstrumentPort:
        return self._instrument


def evidence_kind_of(port: InstrumentPort) -> EvidenceKind:
    """Evidence kind for readings from a port. A device port is MEASURED."""
    kind = getattr(port, "evidence_kind", EvidenceKind.MEASURED)
    if not isinstance(kind, EvidenceKind) or kind is EvidenceKind.NOT_MEASURED:
        raise InstrumentError("a port must declare a usable evidence kind")
    return kind


__all__ = ["SimulatedInstrument", "SimulatedInstrumentSource", "evidence_kind_of"]
