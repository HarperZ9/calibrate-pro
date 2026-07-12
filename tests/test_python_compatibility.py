"""Collection regressions across every supported Python version."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_adapter_collects_without_python_312_monitoring_api() -> None:
    script = textwrap.dedent(
        """
        import sys
        import pytest

        if hasattr(sys, "monitoring"):
            delattr(sys, "monitoring")
        raise SystemExit(
            pytest.main(
                [
                    "--collect-only",
                    "-q",
                    "tests/test_windows_display_state_adapter.py",
                ]
            )
        )
        """
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
