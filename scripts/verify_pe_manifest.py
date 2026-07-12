"""Verify that frozen Windows executables request only as-invoker privileges."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

import pefile

RT_MANIFEST = 24
FORBIDDEN_LEVELS = {"requireAdministrator", "highestAvailable"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resource_payloads(pe: pefile.PE, resource_id: int) -> list[bytes]:
    root = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    if root is None:
        return []
    payloads: list[bytes] = []
    for type_entry in root.entries:
        if type_entry.id != resource_id or not hasattr(type_entry, "directory"):
            continue
        for name_entry in type_entry.directory.entries:
            if not hasattr(name_entry, "directory"):
                continue
            for language_entry in name_entry.directory.entries:
                data = language_entry.data.struct
                payloads.append(pe.get_data(data.OffsetToData, data.Size))
    return payloads


def _decode_manifest(payload: bytes) -> str:
    stripped = payload.rstrip(b"\x00")
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le"):
        try:
            return stripped.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("RT_MANIFEST is not valid UTF-8 or UTF-16 XML")


def verify_executable(path: str | Path) -> dict[str, str]:
    target = Path(path).resolve()
    pe = pefile.PE(str(target), fast_load=False)
    try:
        payloads = _resource_payloads(pe, RT_MANIFEST)
    finally:
        pe.close()
    if len(payloads) != 1:
        raise ValueError(f"{target.name} must contain exactly one RT_MANIFEST; found {len(payloads)}")
    root = ET.fromstring(_decode_manifest(payloads[0]))
    levels = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "requestedExecutionLevel"]
    if len(levels) != 1:
        raise ValueError(f"{target.name} must contain exactly one requestedExecutionLevel")
    level = levels[0].attrib.get("level")
    if level in FORBIDDEN_LEVELS or level != "asInvoker":
        raise ValueError(f"{target.name} requests forbidden execution level: {level}")
    return {"path": target.name, "sha256": _sha256(target), "requested_execution_level": level}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executables", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    receipt = {
        "schema_version": 1,
        "executables": sorted((verify_executable(path) for path in args.executables), key=lambda item: item["path"]),
    }
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
