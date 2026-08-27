"""mcp.py — Calibrate Pro over MCP stdio, a read-only catalog and doctor surface.

An agent (or a Flywheel lane probe) drives Calibrate Pro's deterministic,
device-free knowledge here: the calibration target presets, the characterized
panel database, and a readiness diagnostic. Every tool is read-only and touches
no display: enumerating targets and panels mutates nothing, and the doctor only
inspects installed libraries and pure math.

Actuation stays GUI-gated. The CLI already refuses direct calibrate / verify /
ddc / startup commands and routes them to the interactive preview-and-confirm
workflow; this server exposes none of them, so a remote agent cannot change an
ICC association, a gamma ramp, a DDC/CI value, or a compositor LUT through MCP.

Zero-dependency JSON-RPC 2.0 over stdio, newline-delimited, matching the protocol
the sibling flagships speak. Launch it with ``calibrate-pro mcp`` or
``python -m calibrate_pro.main mcp``.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from calibrate_pro import __version__

MCP_PROTOCOL_VERSION = "2025-06-18"


def _ok(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _text(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _tool_defs() -> list[dict]:
    return [
        {"name": "calibrate-pro.status",
         "description": "Liveness and identity of the Calibrate Pro MCP server "
                        "(name, version, protocol). Device-free health probe.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "calibrate-pro.doctor",
         "description": "Read-only readiness diagnostic: identity, exposed tools, "
                        "and the installation/capability report (no device probe).",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "calibrate-pro.list-targets",
         "description": "The calibration target presets (profiles, white points, "
                        "luminance, gamma/EOTF, gamut). Pure data, no hardware.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "calibrate-pro.list-panels",
         "description": "The characterized panel database (key, name, manufacturer, "
                        "type) used for sensorless calibration estimates.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "calibrate-pro.panel-info",
         "description": "Stored characterization for one panel key: native "
                        "primaries and white point. Estimated for an attached unit.",
         "inputSchema": {"type": "object", "required": ["panel"],
             "properties": {"panel": {"type": "string",
                            "description": "a key from calibrate-pro.list-panels"}}}},
    ]


_TOOL_NAMES = frozenset(t["name"] for t in _tool_defs())


def _status_payload() -> dict:
    return {"ok": True, "server": "calibrate-pro", "version": __version__,
            "protocol": MCP_PROTOCOL_VERSION}


def _doctor_payload() -> dict:
    info = _status_payload()
    info["tools"] = [t["name"] for t in _tool_defs()]
    try:
        from calibrate_pro.diagnostics import build_doctor_report
        info["diagnostics"] = build_doctor_report()
    except Exception as exc:  # doctor reports the fault; it never fails the probe
        info["diagnostics"] = {"ok": None, "error": f"{type(exc).__name__}: {exc}"}
    return info


def _targets_payload() -> dict:
    from calibrate_pro.targets import (
        get_gamma_presets,
        get_gamut_presets,
        get_luminance_presets,
        get_profile_presets,
        get_whitepoint_presets,
    )
    return {
        "profiles": [{"name": p.name, "description": p.description, "hdr": p.is_hdr()}
                     for p in get_profile_presets()],
        "whitepoints": [{"preset": w.preset.value, "cct": round(w.get_cct(), 1)}
                        for w in get_whitepoint_presets()],
        "luminance": [{"standard": m.standard.value,
                       "peak_nits": round(m.get_peak_luminance(), 1), "hdr": m.is_hdr()}
                      for m in get_luminance_presets()],
        "gamma": [{"preset": g.preset.value, "hdr": g.is_hdr()} for g in get_gamma_presets()],
        "gamut": [{"preset": g.preset.value, "wide_gamut": g.is_wide_gamut()}
                  for g in get_gamut_presets()],
    }


def _panels_payload() -> dict:
    from calibrate_pro.panels.database import PanelDatabase
    database = PanelDatabase()
    panels = []
    for key in sorted(database.list_panels()):
        panel = database.get_panel(key)
        if panel is not None:
            panels.append({"key": key, "name": panel.name,
                           "manufacturer": panel.manufacturer, "panel_type": panel.panel_type})
    return {"count": len(panels), "panels": panels}


def _panel_info_payload(key: str) -> dict:
    from calibrate_pro.panels.database import PanelDatabase
    database = PanelDatabase()
    panel = database.get_panel(key) or database.find_panel(key)
    if panel is None:
        raise ValueError(f"no panel {key!r}; use calibrate-pro.list-panels for keys")
    primaries = panel.native_primaries
    return {
        "key": key, "name": panel.name, "manufacturer": panel.manufacturer,
        "panel_type": panel.panel_type,
        "estimate": "characterized estimate for an attached unit, not a live measurement",
        "native_primaries": {
            "red": [primaries.red.x, primaries.red.y],
            "green": [primaries.green.x, primaries.green.y],
            "blue": [primaries.blue.x, primaries.blue.y],
            "white": [primaries.white.x, primaries.white.y]},
    }


def call_tool(name: str, args: dict) -> str:
    if name == "calibrate-pro.status":
        payload = _status_payload()
    elif name == "calibrate-pro.doctor":
        payload = _doctor_payload()
    elif name == "calibrate-pro.list-targets":
        payload = _targets_payload()
    elif name == "calibrate-pro.list-panels":
        payload = _panels_payload()
    elif name == "calibrate-pro.panel-info":
        payload = _panel_info_payload(str(args["panel"]))
    else:
        raise ValueError(f"unknown tool: {name}")
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    mid = req.get("id")
    if "id" not in req:
        return None
    if method == "initialize":
        return _ok(mid, {"protocolVersion": MCP_PROTOCOL_VERSION,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": "calibrate-pro", "version": __version__}})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": _tool_defs()})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        if not isinstance(name, str) or name not in _TOOL_NAMES:
            return _err(mid, -32602, f"unknown tool: {name!r}")
        try:
            return _ok(mid, _text(call_tool(name, params.get("arguments") or {})))
        except Exception as exc:  # tool errors ride the result, not the transport
            return _ok(mid, _text(f"error: {exc}", is_error=True))
    return _err(mid, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_err(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        response = handle_request(request)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
