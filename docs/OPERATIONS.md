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
   | `.streamlit/secrets.toml` | `GH_PAT` | local dev broken |
   | Streamlit Cloud → App settings → Secrets | `GH_PAT` | **production broken** |
   | GitHub repo → Settings → Secrets → Actions | `GH_PAT` | nightly screener + price alerts silently stop |

   **GitHub Actions reserves the `GITHUB_` prefix for secret names too** — not
   just Streamlit Cloud. `screener.yml` read `secrets.GITHUB_REPO` for months;
   that secret could never exist, so it resolved to `""` and
   `push_screener_results()` always failed silently. Both workflows now use
   `PICKR_REPO` (from the built-in `github.repository`, no secret needed) and
   `PICKR_DATA_REPO`.

   **Streamlit Cloud rejects any secret name starting with `GITHUB_`** (reserved
   prefix). Use the Cloud-safe aliases everywhere:

   | Cloud-safe name | Legacy name also accepted | What it is |
   |---|---|---|
   | `GH_PAT` | `GITHUB_TOKEN` | the PAT |
   | `PICKR_REPO` | `GITHUB_REPO` | public code repo |
   | `PICKR_DATA_REPO` | `GITHUB_DATA_REPO` | **private** data repo |

   If `PICKR_DATA_REPO` is unset in production, user data falls back to the
   public repo — where `users.json` no longer exists — so sign-in fails and
   generated reports are never saved to history. `preflight.py` FAILs on it and
   `?_debug=1` shows the resolved values.

5. Verify: `python preflight.py` → all OK.

---

## 2. Separate the private data repo

User data must never sit in the public code repo.

1. Create a **private** repo, e.g. `pickr-data`.
2. Set `PICKR_DATA_REPO=<owner>/pickr-data` in all three locations above.
3. Migrate existing accounts:

   ```bash
   python scripts/reset_password.py migrate --from-file users.json --dry-run
   python scripts/reset_password.py migrate --from-file users.json
   ```

4. Copy `reports/`, `guest_counts.json` and `tracked_stocks.json` into the
   private repo (push them directly, or let the app recreate them — saved
   history is not recoverable if you skip this).
5. Add `PICKR_DATA_REPO` as a **GitHub Actions secret** too (NOT
   `GITHUB_DATA_REPO` — reserved prefix, it would silently be empty).
   `check_prices.py`
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

**Streamlit Cloud runs Python 3.14.6.** Confirmed from a build log:
`Using Python 3.14.6 environment at /home/adminuser/venv`.

`runtime.txt` does **not** work here — a `runtime.txt` pinning 3.12 was added
and the very next build still used 3.14.6, so the file was deleted rather than
left as a false guarantee. Streamlit Community Cloud takes its interpreter from
the app's **Advanced settings** (set at creation; changing it on an existing app
means recreating it), not from a file in the repo.

Actual versions in play:

| Where | Version | Pinned by |
|---|---|---|
| Streamlit Cloud (production) | **3.14.6** | app Advanced settings — not the repo |
| `.github/workflows/screener.yml` | 3.12 | `python-version:` |
| `.github/workflows/daily_check.yml` | 3.12 | `python-version:` |
| local `venv/` | **3.9.6** (EOL Oct 2025) | how the venv was created |

**Known gap:** three different interpreters, and tests run on the oldest. The
pinned `requirements.txt` does install cleanly on 3.14 (verified in the build
log — 66 packages, no errors), and the code is deliberately version-portable
(`typing.Optional`/`List` rather than `X | Y` unions, no `match`, no `tomllib`),
so this is latent rather than active. Closing it means rebuilding the venv on
something current:

```bash
python3.12 -m venv venv --clear      # or 3.14 to match production exactly
./venv/bin/pip install -r requirements.txt
PICKR_OFFLINE=1 ./venv/bin/python -m pytest tests_app_flows.py -q
```

The `NotOpenSSLWarning` in local test output comes from macOS system Python
linking LibreSSL instead of OpenSSL. Cosmetic, local-only, and it disappears
once the venv is rebuilt on a Homebrew/python.org interpreter.

### Cloud caches imported modules — reboot after adding a new one

Streamlit Cloud deploys by `git pull` into a **running** process. It re-executes
`app.py`, but modules already in `sys.modules` are not necessarily re-imported.
Adding a new function to `session_cookie.py` and importing it from `app.py` in
the same push produced:

```
ImportError: cannot import name 'drain_pending_cookie' from 'session_cookie'
```

— new `app.py` against a stale `session_cookie` module. The file on disk was
correct the whole time.

**After any push that adds a name to a non-main module, use Manage app → ⋮ →
Reboot app.** A reboot re-imports everything; an incremental pull may not.

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

---

## 9. The session cookie (read this before touching auth)

Two rules, both learned the hard way — this bug was misdiagnosed twice.

**Reading is server-side.** `st.context.cookies` exposes the cookies sent with
the page request, resolved on the first script run. Use it. Do NOT read through
the `CookieManager` component: it returns `{}` until its iframe mounts, which is
what the old sleep-and-retry hydration gate existed to paper over.

**Writing must happen on a run that COMPLETES.** `mgr.set()` does not write a
cookie — it renders a component whose JavaScript writes `document.cookie` once
the browser mounts the iframe. Calling `st.rerun()` straight afterwards aborts
the run first, so the cookie is never stored. Every auth path did this, so no
session cookie was EVER written, and every reload logged the user out.

Therefore: from any handler that reruns, call `queue_session_cookie()` /
`queue_clear_session_cookie()`. `app.py` drains the queue at the top of the next
run via `drain_pending_cookie()`. On sign-out, set the flag **after** the
session_state wipe or it is wiped too.

**Diagnosing.** Append `?_debug=1` to the app URL for a panel showing context
cookies, component cookies, the token verdict and secret status — presence and
validity only, never values. If the context row says `NO` after signing in and
reloading, the write did not land.

**Never reintroduce `<a href="?_qt=...">` ticker links.** Anchors are full page
reloads that destroy `session_state`. Use `select_ticker()` /
`ticker_chip_row()` in `app.py`. `tests_app_flows.py::TestNoFullPageReloads`
fails if an anchor comes back.

**`PICKR_SESSION_SECRET` must be set** in both `.streamlit/secrets.toml` and
Streamlit Cloud. `config.py` has a fallback literal that lives in the public
repo — leaving it in place lets anyone forge a signed session token for any
user, including admin. `preflight.py` FAILs on it. Rotating it invalidates all
existing sessions, which is a sign-out for everyone, not an outage.
