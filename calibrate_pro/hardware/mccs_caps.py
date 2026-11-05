"""Parse an MCCS capabilities string without losing nested value lists.

A monitor answers a DDC/CI capabilities request with text such as
``vcp(10 12 14(05 08 0B) 16 18 1A)``. A code may carry its permitted values in
a nested group, so a pattern that stops at the first closing parenthesis reads
the values of ``14`` as codes and drops every code after it. A Sceptre K32
answers with exactly that shape, and the old parser reported no RGB gain on a
panel that advertises all three.

This module is pure text handling. It opens no device and imports no Windows
API, so it can be tested on any platform.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_VCP_OPEN = re.compile(r"(?<![a-z0-9_])vcp\(", re.IGNORECASE)
_SIMPLE_GROUP = r"(?<![a-z0-9_]){name}\(([^()]*)\)"


@dataclass(frozen=True)
class ParsedCapabilities:
    """The parts of a capabilities string the calibration loop reads."""

    codes: tuple[int, ...] = ()
    values: dict[int, tuple[int, ...]] = field(default_factory=dict)
    model: str = ""
    mccs_version: str = ""
    display_type: str = ""


def _hex_tokens(text: str) -> list[int]:
    """Read whitespace-separated hex tokens, skipping any that are not hex."""
    found: list[int] = []
    for token in text.split():
        try:
            found.append(int(token, 16))
        except ValueError:
            continue
    return found


def _vcp_body(raw: str) -> str:
    """Return the text inside the top-level ``vcp(...)`` group, balanced."""
    match = _VCP_OPEN.search(raw)
    if match is None:
        return ""
    depth = 1
    start = match.end()
    for index in range(start, len(raw)):
        char = raw[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return raw[start:index]
    return raw[start:]


def _split_codes(body: str) -> tuple[list[int], dict[int, tuple[int, ...]]]:
    """Split a vcp body into codes and the value list each code advertises."""
    codes: list[int] = []
    values: dict[int, tuple[int, ...]] = {}
    token = ""
    index = 0
    while index < len(body):
        char = body[index]
        if char == "(":
            close = body.find(")", index)
            close = len(body) if close < 0 else close
            owner = _hex_tokens(token)
            if owner:
                codes.extend(owner)
            elif codes:
                owner = [codes[-1]]
            if owner:
                values[owner[-1]] = tuple(_hex_tokens(body[index + 1 : close]))
            token = ""
            index = close + 1
            continue
        if char.isspace():
            codes.extend(_hex_tokens(token))
            token = ""
        else:
            token += char
        index += 1
    codes.extend(_hex_tokens(token))
    return codes, values


def _simple_group(raw: str, name: str) -> str:
    match = re.search(_SIMPLE_GROUP.format(name=name), raw, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_capabilities(raw: str) -> ParsedCapabilities:
    """Parse the codes, value lists, model, MCCS version and type of a panel."""
    if not isinstance(raw, str):
        raise TypeError("raw capabilities must be a string")
    codes, values = _split_codes(_vcp_body(raw))
    unique: list[int] = []
    for code in codes:
        if code not in unique:
            unique.append(code)
    return ParsedCapabilities(
        codes=tuple(unique),
        values=values,
        model=_simple_group(raw, "model"),
        mccs_version=_simple_group(raw, "mccs_ver"),
        display_type=_simple_group(raw, "type"),
    )


__all__ = ["ParsedCapabilities", "parse_capabilities"]
