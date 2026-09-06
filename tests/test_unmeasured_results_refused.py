"""An operation that never ran must not hand back a number for it.

Several paths used to answer with invented values. The fleet server queued jobs
for remote nodes, ran a stub that slept and returned ``delta_e_mean: 1.2`` with
``passed: True``, stored that under the node id, and marked the job COMPLETED.
The ambient sensor base class and the Windows sensor both returned 300 lux from
a sensor neither of them reads. The spectrophotometer answered 95.0 for CRI and
90.0 for TLCI whatever spectrum it was handed, and returned an emissive spot
reading when asked for a reflective one. The fleet server answered True to
every profile push, so the sync manager filed packages as delivered to nodes
that received nothing. In each case the record that came out is shaped exactly
like a record built from a real reading, so nothing downstream can tell the
difference.

PRODUCT.md: the interface must never convert modeled, simulated, replayed, or
placeholder values into apparent instrument observations. These tests hold the
refusals in place, and keep the honestly named stand-ins working.
"""

from __future__ import annotations

import asyncio

import pytest

from calibrate_pro.advanced.ambient_light import (
    AmbientSensor,
    SimulatedSensor,
    WindowsLightSensor,
)
from calibrate_pro.advanced.network_calibration import (
    CalibrationServer,
    DisplayNode,
    JobStatus,
    JobType,
    NodeStatus,
    ProfilePackage,
    ProfileSyncManager,
)
from calibrate_pro.hardware.colorimeter_base import DeviceInfo, DeviceType
from calibrate_pro.hardware.spectro import SpectrophotometerDriver

#: The value the fleet stubs used to report for a display nobody measured.
FABRICATED_DELTA_E = 1.2

#: The value both ambient sensors used to report for a room nobody sampled.
FABRICATED_LUX = 300


@pytest.fixture
def server():
    """A server holding one reachable node, with no transport to it."""
    srv = CalibrationServer(host="127.0.0.1", port=0, server_id="test-server")
    srv.register_node(
        DisplayNode(
            node_id="node-1",
            hostname="studio-1",
            ip_address="10.0.0.11",
            display_name="Studio 1",
            status=NodeStatus.ONLINE,
        )
    )
    yield srv
    srv._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Fleet jobs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "operation"),
    [
        ("_run_calibration", "Full calibration"),
        ("_run_verification", "Verification"),
        ("_apply_profile", "Profile apply"),
        ("_apply_lut", "LUT apply"),
        ("_run_measurement", "Measurement"),
    ],
)
def test_remote_operation_refuses_instead_of_returning_a_result(server, method, operation):
    """Each remote stub raises, and names the operation and the node."""
    node = server.get_node("node-1")

    with pytest.raises(NotImplementedError) as raised:
        asyncio.run(getattr(server, method)(node, {}))

    message = str(raised.value)
    assert operation in message
    assert "node-1" in message


def test_unreachable_node_fails_the_job_rather_than_completing_it(server):
    """A job over a node the server cannot reach ends FAILED, carrying no result.

    The failure mode this replaces: a fleet operator reads a Delta E for a
    display that was never put in front of an instrument.
    """
    job = server.create_job(job_type=JobType.FULL_CALIBRATION, target_nodes=["node-1"])
    server._running = True

    asyncio.run(server.process_jobs())

    assert job.status is JobStatus.FAILED
    assert job.results == {}
    assert "node-1" in job.errors
    assert "not implemented" in job.errors["node-1"]


def test_no_fleet_path_reports_a_delta_e(server):
    """No job record carries a Delta E, mean or otherwise, from a stub."""
    job = server.create_job(job_type=JobType.VERIFICATION_ONLY, target_nodes=["node-1"])
    server._running = True

    asyncio.run(server.process_jobs())

    recorded = str(job.results) + str(job.errors)
    assert "delta_e" not in recorded
    assert str(FABRICATED_DELTA_E) not in recorded


def test_node_returns_to_online_after_a_refused_job(server):
    """The refusal travels through the ``finally`` that restores node status."""
    job = server.create_job(job_type=JobType.MEASUREMENT, target_nodes=["node-1"])
    server._running = True

    asyncio.run(server.process_jobs())

    assert job.status is JobStatus.FAILED
    assert server.get_node("node-1").status is NodeStatus.ONLINE


# ---------------------------------------------------------------------------
# Ambient light
# ---------------------------------------------------------------------------


def test_base_sensor_reads_nothing_and_says_so():
    """``AmbientSensor`` is an interface, so reading one raises."""
    with pytest.raises(NotImplementedError) as raised:
        AmbientSensor().read()

    assert "SimulatedSensor" in str(raised.value)


def test_windows_sensor_is_unavailable_and_refuses_to_read():
    """The Windows.Devices.Sensors binding is absent, so nothing is reported."""
    sensor = WindowsLightSensor()

    assert sensor.is_available is False
    with pytest.raises(RuntimeError) as raised:
        sensor.read()

    assert "unavailable" in str(raised.value)


def test_neither_sensor_answers_with_a_nominal_room_level():
    """Nothing returns the old 300 lux stand-in as though a sensor produced it."""
    for sensor in (AmbientSensor(), WindowsLightSensor()):
        with pytest.raises((NotImplementedError, RuntimeError)):
            sensor.read()


def test_simulated_sensor_still_reads():
    """The honestly named stand-in keeps working, which is where a value belongs."""
    reading = SimulatedSensor(base_lux=FABRICATED_LUX).read()

    assert reading.lux > 0
    assert reading.cct > 0


# ---------------------------------------------------------------------------
# Spectral metrics
# ---------------------------------------------------------------------------


#: A flat spectrum. Any two of these metrics would differ on it, so a method
#: that answers the same number for every input is not reading it at all.
FLAT_SPECTRUM = {float(nm): 1.0 for nm in range(380, 781, 10)}

#: The indices the two metrics used to report for any spectrum handed to them.
FABRICATED_CRI = 95.0
FABRICATED_TLCI = 90.0


@pytest.fixture
def spectro():
    """A spectrophotometer with no ArgyllCMS behind it."""
    return SpectrophotometerDriver()


def test_cri_refuses_rather_than_reporting_a_fixed_index(spectro):
    """CIE 13.3 is not implemented, so no rendering index is reported."""
    with pytest.raises(NotImplementedError) as raised:
        spectro.calculate_cri(FLAT_SPECTRUM)

    assert str(FABRICATED_CRI) in str(raised.value)


def test_tlci_refuses_rather_than_reporting_a_fixed_index(spectro):
    """The camera model and the reference comparison are both absent."""
    with pytest.raises(NotImplementedError) as raised:
        spectro.calculate_tlci(FLAT_SPECTRUM)

    assert str(FABRICATED_TLCI) in str(raised.value)


def test_reflective_measurement_refuses_on_a_device_that_offers_it(spectro):
    """An emissive reading is a measurement of the display, not of the material."""
    spectro.device_info = DeviceInfo(
        name="i1Pro 3",
        manufacturer="X-Rite",
        model="i1Pro3",
        serial="TEST",
        device_type=DeviceType.SPECTROPHOTOMETER,
        capabilities=["spectral", "emission", "reflective"],
    )

    with pytest.raises(NotImplementedError) as raised:
        spectro.measure_reflective()

    assert "emissive" in str(raised.value)


def test_reflective_measurement_still_returns_none_without_the_capability(spectro):
    """A device that cannot do it answers None, which is the honest empty result."""
    spectro.device_info = DeviceInfo(
        name="i1Display Pro",
        manufacturer="X-Rite",
        model="i1d3",
        serial="TEST",
        device_type=DeviceType.COLORIMETER,
        capabilities=["emission"],
    )

    assert spectro.measure_reflective() is None


# ---------------------------------------------------------------------------
# Profile distribution
# ---------------------------------------------------------------------------


def _package() -> ProfilePackage:
    return ProfilePackage(
        package_id="pkg-1",
        name="Studio D65",
        version="1.0.0",
        icc_profile=b"not a real profile",
    )


def test_pushing_a_profile_reports_failure_when_nothing_carries_it(server):
    """There is no transport to a node, so no node is told the push succeeded."""
    server.add_profile(_package())

    results = server.push_profile_to_nodes("pkg-1", ["node-1"])

    assert results == {"node-1": False}


def test_sync_records_an_error_rather_than_listing_the_profile_as_synced(server):
    """``sync_all`` used to file a package under ``synced_profiles`` for a node
    that received nothing, and report no sync errors alongside it.

    A fleet operator reading that state concludes the display is running the
    profile named there. Nothing was sent, so the display is running whatever it
    had before.
    """
    server.add_profile(_package())

    state = ProfileSyncManager(server).sync_all()

    assert state.synced_profiles == []
    assert len(state.sync_errors) == 1
    assert "node-1" in state.sync_errors[0]
    assert "Studio D65" in state.sync_errors[0]
