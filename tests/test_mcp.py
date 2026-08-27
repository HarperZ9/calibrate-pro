"""The Calibrate Pro MCP server: read-only catalog + doctor, no actuation."""

import io
import json

import pytest

from calibrate_pro import __version__
from calibrate_pro.main import _CONFIRMATION_COMMANDS
from calibrate_pro.mcp import (
    MCP_PROTOCOL_VERSION,
    _tool_defs,
    call_tool,
    handle_request,
    serve,
)


def _call(name, args=None):
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": name, "arguments": args or {}}}
    result = handle_request(req)["result"]
    text = result["content"][0]["text"]
    return result, text


# --- protocol handshake ---

def test_initialize_advertises_identity_and_protocol():
    res = handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})["result"]
    assert res["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert res["serverInfo"] == {"name": "calibrate-pro", "version": __version__}


def test_notification_gets_no_response():
    assert handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_is_json_rpc_error():
    res = handle_request({"jsonrpc": "2.0", "id": 2, "method": "nope"})
    assert res["error"]["code"] == -32601


def test_tools_list_exposes_the_health_probe():
    res = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]
    names = {t["name"] for t in res["tools"]}
    # the Flywheel lane probe looks for exactly this tool name
    assert "calibrate-pro.status" in names
    assert "calibrate-pro.doctor" in names


# --- the health probe answers (this is what makes the lane LIVE) ---

def test_status_answers_without_error():
    result, text = _call("calibrate-pro.status")
    assert result.get("isError") is False
    payload = json.loads(text)
    assert payload["ok"] is True
    assert payload["server"] == "calibrate-pro"
    assert payload["protocol"] == MCP_PROTOCOL_VERSION


def test_doctor_answers_and_carries_a_diagnostics_report():
    result, text = _call("calibrate-pro.doctor")
    assert result.get("isError") is False
    payload = json.loads(text)
    assert payload["ok"] is True  # the doctor ran; diagnostics.ok is a separate verdict
    assert "diagnostics" in payload
    assert set(payload["tools"]) == {t["name"] for t in _tool_defs()}


# --- read-only catalog ---

def test_list_targets_returns_structured_presets():
    payload = json.loads(call_tool("calibrate-pro.list-targets", {}))
    assert payload["profiles"] and payload["whitepoints"]
    assert {"name", "description", "hdr"} <= set(payload["profiles"][0])
    assert any(p["hdr"] for p in payload["profiles"])  # at least one HDR profile


def test_list_panels_then_panel_info_roundtrip():
    panels = json.loads(call_tool("calibrate-pro.list-panels", {}))
    assert panels["count"] == len(panels["panels"]) >= 1
    key = panels["panels"][0]["key"]
    info = json.loads(call_tool("calibrate-pro.panel-info", {"panel": key}))
    assert info["key"] == key
    assert set(info["native_primaries"]) == {"red", "green", "blue", "white"}


def test_panel_info_on_unknown_key_rides_the_result_as_an_error():
    result, text = _call("calibrate-pro.panel-info", {"panel": "NO_SUCH_PANEL_XYZ"})
    assert result["isError"] is True
    assert "no panel" in text


def test_unknown_tool_is_a_param_error():
    res = handle_request({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                          "params": {"name": "calibrate-pro.calibrate"}})
    assert res["error"]["code"] == -32602


# --- the actuation boundary: no confirmation command is reachable over MCP ---

def test_no_actuation_command_is_exposed_as_a_tool():
    tool_names = {t["name"] for t in _tool_defs()}
    read_only = {"calibrate-pro.status", "calibrate-pro.doctor",
                 "calibrate-pro.list-targets", "calibrate-pro.list-panels",
                 "calibrate-pro.panel-info"}
    assert tool_names == read_only  # the server exposes ONLY these read-only tools
    for command in _CONFIRMATION_COMMANDS:
        # The CLI's confirmation commands actuate a display and route to GUI preview.
        # None are wired here. ("status" collides by name with the read-only health
        # probe -- a liveness report, not the CLI's GUI-monitor command.)
        if f"calibrate-pro.{command}" in read_only:
            continue
        assert command not in tool_names
        with pytest.raises(ValueError):
            call_tool(f"calibrate-pro.{command}", {})


# --- the stdio loop frames one JSON object per line ---

def test_serve_reads_and_writes_newline_delimited_json():
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    stdout = io.StringIO()
    serve(stdin=io.StringIO(json.dumps(request) + "\n"), stdout=stdout)
    lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert any(t["name"] == "calibrate-pro.status"
               for t in json.loads(lines[0])["result"]["tools"])
