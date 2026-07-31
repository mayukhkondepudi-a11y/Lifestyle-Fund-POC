"""Test seam: run the real app.py without touching the network.

Why a seam is needed
--------------------
The flows that broke in production — sign-in, guest limits, screener
rendering, report persistence — are *application* behaviour, not analytical
behaviour. The engine suite (tests_methodology.py et al.) proves the maths;
nothing proved that an expired token turns into a sensible screen instead of
"Invalid username or password". Testing that requires running app.py itself,
which means FMP, Anthropic and GitHub all have to be substitutable.

Everything here is inert unless ``PICKR_OFFLINE=1``, so production behaviour
is untouched.

Environment switches
--------------------
``PICKR_OFFLINE=1``          enable the seam
``PICKR_OFFLINE_DIR=<path>`` directory backing the fake GitHub store
``PICKR_OFFLINE_GH=<mode>``  ``local`` (default) | ``broken`` | ``absent``
                             ``broken`` simulates the expired-PAT outage —
                             the single most important case to regression-test.
``PICKR_OFFLINE_FAIL=1``     make report generation raise, to prove a failed
                             report shows a failure card and costs no quota.
``PICKR_OFFLINE_TICKER``     which fixture report to serve (default CLS)
"""
import json
import os
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "tests" / "fixtures" / "app_flows"


def enabled() -> bool:
    return os.environ.get("PICKR_OFFLINE") == "1"


def gh_mode() -> str:
    return os.environ.get("PICKR_OFFLINE_GH", "local")


def should_fail_generation() -> bool:
    return os.environ.get("PICKR_OFFLINE_FAIL") == "1"


def store_dir() -> Path:
    d = Path(os.environ.get("PICKR_OFFLINE_DIR", "/tmp/pickr_offline_store"))
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Fake GitHub store ─────────────────────────────────────────
# gh_api dispatches here when the seam is on, so every persistence path
# (users, guest counts, reports, screener) is exercised for real against a
# local directory — including its failure modes.

def gh_read(filepath):
    """Return (status, content, sha) mirroring gh_api's classification."""
    mode = gh_mode()
    if mode == "broken":
        return "auth_error", None, None
    if mode == "absent":
        return "absent", None, None

    p = store_dir() / filepath
    if not p.exists():
        return "absent", None, None
    try:
        content = json.loads(p.read_text())
    except Exception as exc:
        return "parse_error", None, None
    # sha is only used for optimistic concurrency; mtime is a fine stand-in.
    return "ok", content, str(p.stat().st_mtime)


def gh_write(filepath, content):
    mode = gh_mode()
    if mode == "broken":
        return "auth_error", None
    p = store_dir() / filepath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(content, indent=2, default=str))
    return "ok", str(p.stat().st_mtime)


def gh_probe():
    mode = gh_mode()
    if mode == "broken":
        return "auth_error", None
    # Report the data repo as private so preflight's exposure check passes.
    return "ok", {"private": True, "full_name": "offline/pickr-data"}


def seed_user(username, name, email, password, report_count=0):
    """Write a real bcrypt-hashed user into the fake store."""
    import bcrypt
    status, users, _ = gh_read("users.json")
    if status != "ok" or not isinstance(users, dict):
        users = {}
    users[username] = {
        "name": name,
        "email": email,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "report_count": report_count,
    }
    # Write directly: gh_write honours "broken" mode, which seeding must not.
    p = store_dir() / "users.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(users, indent=2))
    return users


def reset_store():
    """Remove every file in the fake store (call between tests)."""
    import shutil
    d = store_dir()
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)


# ── Fixture report ────────────────────────────────────────────

def _fixture_path(ticker=None):
    t = (ticker or os.environ.get("PICKR_OFFLINE_TICKER", "CLS")).upper()
    p = FIXTURE_DIR / f"report_{t}.json"
    return p if p.exists() else FIXTURE_DIR / "report_CLS.json"


def load_fixture(ticker=None):
    """A real saved report: {'metrics': {...}, 'analysis': {...}}."""
    return json.loads(_fixture_path(ticker).read_text())


def generate(ticker):
    """Stand in for the whole fetch → calc → run_pipeline chain.

    Returns (metrics, analysis, source_data). Raises RuntimeError when
    PICKR_OFFLINE_FAIL=1 so the app's failure path can be asserted — that path
    previously surfaced as a raw traceback after the user had already been
    charged for the report.
    """
    if should_fail_generation():
        raise RuntimeError("simulated pipeline failure (PICKR_OFFLINE_FAIL=1)")
    fx = load_fixture(ticker)
    metrics = dict(fx.get("metrics", {}))
    metrics.setdefault("company_name", ticker)
    analysis = fx.get("analysis", {})
    source_data = {"hist": None, "info": {"shortName": metrics.get("company_name", ticker),
                                          "_source": "offline-fixture"},
                   "inc": None, "qinc": None, "bs": None, "cf": None, "news": []}
    return metrics, analysis, source_data
