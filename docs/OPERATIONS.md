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
   | GitHub repo → Settings → Secrets → Actions | `GH_PAT` | nightly screener silently stops |

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

4. Copy `reports/` and `guest_counts.json` into the private repo (push them
   directly, or let the app recreate them — history is not recoverable if you
   skip this).
5. Confirm `preflight.py` reports **"reachable and private"** for the data repo.
   It fails loudly if the data repo is public or if `GITHUB_DATA_REPO` is unset
   and user data is falling back to the public repo.

`users.json`, `guest_counts.json` and `reports/` are now in `.gitignore` and
untracked. They are written at runtime through the GitHub API, never committed.

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

## 5. Upgrading dependencies

`requirements.txt` is pinned. It previously had no constraints at all, so a
Streamlit Cloud rebuild could break production with no code change.

Bump **one** pin at a time, redeploy, run `tests_app_flows.py`. Bumping several
at once reintroduces exactly the ambiguity the pins remove. `yfinance` and
`extra-streamlit-components` are the usual culprits — the latter is coupled to
Streamlit internals, so bump it together with `streamlit` and test the cookie
flow (sign in, reload, confirm you are still signed in).

---

## 6. The nightly screener

`.github/workflows/screener.yml` runs at 10:00 UTC and pushes
`screener_results.json`. It uses the `GH_PAT` Actions secret — the same token as
the app, so it dies from the same rotation.

If picks are stale, the app shows a staleness warning after 3 days and
`preflight.py` flags it. Check the Actions tab first; a failed run is almost
always the token.

---

## 7. Design rule for future changes

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
