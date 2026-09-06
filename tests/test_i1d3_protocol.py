"""Protocol-level tests for the native i1Display3 measurement path."""

from __future__ import annotations

import struct

import pytest

from calibrate_pro.hardware.i1d3_native import I1D3Driver


class FakeHidTransport:
    def __init__(self, counts: tuple[int, int, int]) -> None:
        response = bytearray(64)
        response[0] = 0x00
        response[1] = 0x01
        struct.pack_into("<III", response, 2, *counts)
        self._response = bytes(response)
        self.last_report = b""

    def write(self, report: bytes) -> int:
        self.last_report = bytes(report)
        return len(report)

    def read(self, size: int, timeout_ms: int) -> list[int]:
        assert size == 64
        assert timeout_ms >= 4_000
        return list(self._response)


class FakeUnlockTransport:
    def __init__(self) -> None:
        challenge = bytearray(64)
        challenge[2] = 0x5A
        challenge[3] = 0x11
        challenge[35:43] = bytes.fromhex("10 20 30 40 50 60 70 80")
        accepted = bytearray(64)
        accepted[2] = 0x77
        self._responses = [bytes(challenge), bytes(accepted)]
        self.reports: list[bytes] = []

    def write(self, report: bytes) -> int:
        self.reports.append(bytes(report))
        return len(report)

    def read(self, size: int, timeout_ms: int) -> list[int]:
        return list(self._responses.pop(0))


def _driver(transport: FakeHidTransport) -> I1D3Driver:
    driver = I1D3Driver(transport=transport)
    driver._integration_time = 1.0
    driver._cal_matrix = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    driver._black_offset = [0.0, 0.0, 0.0]
    return driver


def test_measurement_uses_verified_clock_framing_and_little_endian_counts() -> None:
    transport = FakeHidTransport((12_914, 10_000, 8_000))
    driver = _driver(transport)

    measurement = driver.measure()

    assert measurement is not None
    assert transport.last_report[1] == 0x01
    assert transport.last_report[2:6] == struct.pack("<I", 12_000_000)
    assert measurement.red_count == pytest.approx(0.5 * (12_914 + 0.5))
    assert measurement.green_count == pytest.approx(0.5 * (10_000 + 0.5))
    assert measurement.blue_count == pytest.approx(0.5 * (8_000 + 0.5))


def test_measurement_rejects_physically_impossible_luminance() -> None:
    transport = FakeHidTransport((1, 1_000_000, 1))
    driver = _driver(transport)

    assert driver.measure() is None


def test_challenge_response_unlock_uses_verified_nec_oem_exchange() -> None:
    transport = FakeUnlockTransport()
    driver = I1D3Driver(transport=transport)

    assert driver.unlock() is True
    assert len(transport.reports) == 2
    assert len(transport.reports[0]) == 65
    assert transport.reports[0][1] == 0x99
    assert transport.reports[1][1] == 0x9A
    assert any(transport.reports[1][25:41])
