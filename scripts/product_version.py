"""The one place release tooling learns which version it is building.

`calibrate_pro/__init__.py` declares `__version__` and `pyproject.toml` reads it
through `version = {attr = "calibrate_pro.__version__"}`. Every artifact name,
asset list and build gate in this directory derives from the same declaration so
a version bump is one edit rather than a sweep that a stale copy can survive.

The declaration is parsed rather than imported. Release tooling runs before the
package is installed and against interpreters that have no third-party
dependency available, so importing the package here would couple the build to a
working environment it is trying to produce.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: `scripts/` sits directly under the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DECLARATION = _REPO_ROOT / "calibrate_pro" / "__init__.py"


def read_product_version(declaration: Path | None = None) -> str:
    """Return the `__version__` string `calibrate_pro/__init__.py` declares.

    Raises rather than guessing. A build that cannot read its own version has
    nothing to name its artifacts after, and a default would name them wrongly.
    """
    path = declaration or _DECLARATION
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                value = ast.literal_eval(node.value)
                if not isinstance(value, str) or not value:
                    raise ValueError(f"{path} declares a non-string __version__")
                return value
    raise ValueError(f"{path} declares no __version__")


PRODUCT_VERSION = read_product_version()

#: The four release artifacts whose names carry the version.
PORTABLE_NAME = f"CalibratePro-{PRODUCT_VERSION}-win64.zip"
INSTALLER_NAME = f"CalibratePro-{PRODUCT_VERSION}-Setup.exe"
WHEEL_NAME = f"calibrate_pro-{PRODUCT_VERSION}-py3-none-any.whl"
SDIST_NAME = f"calibrate_pro-{PRODUCT_VERSION}.tar.gz"


if __name__ == "__main__":  # pragma: no cover - CLI boundary for shell callers
    print(PRODUCT_VERSION)
