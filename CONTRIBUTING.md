# Contributing

This repository is part of the Project Telos public surface. Keep changes small, tested, and easy for public users and developers to verify.

Before sending a change:

- Read `README.md` and any local `AGENTS.md` instructions.
- Run the narrowest test or verification command that covers the change.
- Keep examples, package metadata, and public claims aligned with current behavior.
- Do not commit secrets, `.env` files, private corpus material, or generated caches.

## Running the tests

Install the package with the extras the suite needs:

```bash
pip install -e ".[all,test]"
```

On Windows, run everything:

```bash
pytest tests/ -q
```

Elsewhere, deselect the tests that need a Windows runtime:

```bash
pytest tests/ -q -m "not windows"
```

The `windows` marker means a test reaches something only Windows supplies, such
as a `ctypes.windll` entry point or the per-user application directory that
holds the diagnostics journal. Deselecting by that marker on Windows still runs
against a Windows runtime, so a pass there says nothing about the Linux job.
Check that on Linux, or let CI check it for you.

A Linux environment also needs the Qt runtime libraries and Tk, which the
GitHub runners install for you:

```bash
sudo apt-get install -y libegl1 libxkbcommon0 python3-tk
```

CI runs both lanes on Python 3.10, 3.11, 3.12, and 3.13, on Ubuntu and Windows.
