# PickR Operations Runbook

Everything an operator needs to keep PickR healthy, and the exact steps for the
2026-07-31 credential/exposure incident.

**First command to run when anything looks wrong:**

```bash
python preflight.py
```

It names the failing dependency and the remedy, and exits non-zero on failure.
It was written because a single expired token once broke four features at once
with no signal anywhere.

---

## 1. Rotate the GitHub PAT

**Symptoms of a dead token:** sign-in says "temporarily unavailable"; the
screener shows its degraded card; history shows "History unavailable"; admins
see a SYSTEM HEALTH banner. `preflight.py` reports `GitHub token: REJECTED`.

1. Revoke the old token at <https://github.com/settings/tokens>.
2. Create a **fine-grained** PAT with **Contents: Read and write** on both:
   - the public code repo (`GITHUB_REPO`)
   - the private data repo (`GITHUB_DATA_REPO`)
3. Set an expiry you will actually notice, and put a calendar reminder a week
   before it. Silent expiry is what caused the incident.
4. Update the token in **all three** places — missing one leaves a partial
   outage that is harder to diagnose than a total one:

   | Where | Key | Effect if stale |
   |---|---|---|
   | `.streamlit/secrets.toml` | `GITHUB_TOKEN` | local dev broken |
   | Streamlit Cloud → App settings → Secrets | `GITHUB_TOKEN` | **production broken** |
   | GitHub repo → Settings → Secrets → Actions | `GH_PAT` | nightly screener + price alerts silently stop |

5. Verify: `python preflight.py` → all OK.

---

## 2. Separate the private data repo

User data must never sit in the public code repo.

1. Create a **private** repo, e.g. `pickr-data`.
2. Set `GITHUB_DATA_REPO=<owner>/pickr-data` in all three locations above.
3. Migrate existing accounts:

   ```bash
   python scripts/reset_password.py migrate --from-file users.json --dry-run
   python scripts/reset_password.py migrate --from-file users.json
   ```

4. Copy `reports/`, `guest_counts.json` and `tracked_stocks.json` into the
   private repo (push them directly, or let the app recreate them — saved
   history is not recoverable if you skip this).
5. Add `GITHUB_DATA_REPO` as a **GitHub Actions secret** too. `check_prices.py`
   reads the tracker, so without it the nightly alert job finds an empty
   tracker and sends nothing, silently.
6. Confirm `preflight.py` reports **"reachable and private"** for the data repo.
   It fails loudly if the data repo is public or if `GITHUB_DATA_REPO` is unset
   and user data is falling back to the public repo.

Four files are user data and are now `.gitignore`d and untracked. They are
written at runtime through the GitHub API, never committed:

| File | Sensitivity |
|---|---|
| `users.json` | emails + bcrypt password hashes |
| `reports/` | users' saved research |
| `tracked_stocks.json` | `user_email` on every entry |
| `guest_counts.json` | hashed fingerprints only, but belongs with the rest |

`screener_results.json` stays in the public repo — stock picks are not sensitive
and the nightly Action pushes them there.

---

## 3. Password reset after the exposure

`users.json` was tracked in a public repo, so its bcrypt hashes and the
associated email addresses were world-readable, **including in git history**.
Rotating the file does not undo that. Treat every pre-2026-07-31 password as
compromised.

```bash
python scripts/reset_password.py list
python scripts/reset_password.py reset <username> --generate
```

Then tell each user their password was reset and why. Four accounts were
affected: `mayukhk`, `mayukh151`, `mayukh123`, `mayukh1`.

Two of those (`mayukh151` → `kmayukh@amazon.com`, `mayukh1` → `M@gmail.com`)
may be your own test accounts. Delete rather than reset any that are — fewer
live credentials is strictly better.

**Optional:** purging the hashes from git history needs `git filter-repo` and a
force-push that breaks every existing clone. With four known accounts, resetting
passwords is the proportionate remedy; purge only if the emails themselves are
a concern.

---

## 4. Before every deploy

```bash
# Engine (deterministic maths) — expect 306 passed, 4 skipped, 4 deselected
pytest tests_methodology.py tests_golden_math.py tests_scenario_core.py \
       tests_audit_checks.py tests_signal_snapshot.py -m "not live"

# App flows (real app, no network) — expect 23 passed
PICKR_OFFLINE=1 pytest tests_app_flows.py

# Dependencies
python preflight.py
```

Note: `tests_*.py` are not picked up by bare `pytest` — pass them explicitly.

Manual pass in a fresh incognito window:

1. Logged-out landing → screener picks visible, no error banner.
2. Sign in → succeeds; history populates.
3. Sign out → reload → still signed out.
4. Guest → one report → renders; reload → **report still there**; second
   attempt → upgrade CTA.
5. **The acceptance test:** temporarily set a bad `GITHUB_TOKEN`. You must see a
   banner, "temporarily unavailable" on sign-in, and the screener's degraded
   card. No blank sections, no traceback. Restore the token afterwards.

---

## 5. Python version

`runtime.txt` pins Streamlit Cloud to **3.12**, and both workflows now specify
the same. Previously production ran whatever default Streamlit Cloud happened to
pick — the same class of drift as unpinned dependencies, and just as invisible.

Keep these three in step when changing it:

| File | Setting |
|---|---|
| `runtime.txt` | `3.12` (Streamlit Cloud) |
| `.github/workflows/screener.yml` | `python-version: '3.12'` |
| `.github/workflows/daily_check.yml` | `python-version: '3.12'` |

**Known gap:** the local `venv/` is Python 3.9.6, which reached end-of-life in
October 2025. Tests therefore pass on a version nothing else runs. The code is
deliberately version-portable (`typing.Optional`/`List` rather than `X | Y`
unions, no `match`, no `tomllib`), so this is a latent risk rather than an
active one — but rebuilding the venv on 3.12 closes it:

```bash
python3.12 -m venv venv --clear
./venv/bin/pip install -r requirements.txt
PICKR_OFFLINE=1 ./venv/bin/python -m pytest tests_app_flows.py -q
```

The `NotOpenSSLWarning` in local test output comes from macOS system Python
linking LibreSSL instead of OpenSSL. It is cosmetic, local-only, and disappears
once the venv is rebuilt on a Homebrew/python.org 3.12.

## 6. Upgrading dependencies

`requirements.txt` is pinned. It previously had no constraints at all, so a
Streamlit Cloud rebuild could break production with no code change.

Bump **one** pin at a time, redeploy, run `tests_app_flows.py`. Bumping several
at once reintroduces exactly the ambiguity the pins remove. `yfinance` and
`extra-streamlit-components` are the usual culprits — the latter is coupled to
Streamlit internals, so bump it together with `streamlit` and test the cookie
flow (sign in, reload, confirm you are still signed in).

---

## 7. The nightly screener

`.github/workflows/screener.yml` runs at 10:00 UTC and publishes
`screener_results.json` by **two independent paths**:

1. `screener.py` calls `push_screener_results()`, which writes via the GitHub
   API using `GH_PAT`.
2. The workflow then does `git add / commit / push` using the Actions checkout
   credentials — which do **not** depend on `GH_PAT`.

That redundancy matters, and it is why the July 2026 outage looked worse than it
was. When the PAT expired, path 1 failed but path 2 kept publishing, so the data
in the repo stayed current. The screener *looked* broken in the app purely
because the app could no longer **read** it — the writer was fine the whole time.

So when picks look stale, check in this order:

1. `python preflight.py` — is this a read problem (token) or a write problem?
2. The Actions tab — did the run itself fail?

The app shows a staleness warning after 3 days, and `preflight.py` reports the
age. Do not assume stale picks mean a failed Action; confirm which side is
broken before rotating anything.

---

## 8. Design rule for future changes

The incident had one cause worth stating plainly:

> **"The file is absent" and "I could not reach the store" must never collapse
> into the same value.**

`gh_api.GhResult` carries that distinction (`.ok` / `.absent` / `.broken`).
Any new persistence path must branch on `.broken` before treating an empty
result as genuinely empty. `gh_get_json()` / `gh_put_json()` are legacy shims
that erase the distinction — do not use them for anything a user can see.

When adding a code path that can fail, ask: *if this dependency is down, what
does the user see?* If the answer is "the feature just isn't there", it is
wrong.
