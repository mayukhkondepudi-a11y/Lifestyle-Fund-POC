"""Pytest bootstrap for the test suite.

The tests live in tests/ but import application modules (compute, ai, app, ...)
that sit at the repo root — that is deliberate: Streamlit Cloud runs `app.py`
from the root and both GitHub Actions run `python screener.py` from there, so
moving the app into a package would mean reconfiguring the deployment.

This puts the repo root on sys.path so `import compute` resolves, and pins the
working directory to the root so any CWD-relative file access behaves exactly as
it does in production.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

# Root first (application modules), then tools/ — tests_methodology.py imports
# smoke_harness, which is test/dev tooling rather than part of the running app.
for p in (str(ROOT), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.chdir(ROOT)
