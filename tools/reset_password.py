#!/usr/bin/env python3
"""Admin CLI for the PickR account store.

Needed because users.json (real emails + bcrypt hashes) was tracked in a
PUBLIC repo until 2026-07-31. Those hashes must be treated as compromised, so
every existing account needs a new password.

Reads config from .streamlit/secrets.toml or the environment, exactly like the
app does. Run from the repo root.

    python scripts/reset_password.py list
    python scripts/reset_password.py reset <username>
    python scripts/reset_password.py reset <username> --password 'new-password'
    python scripts/reset_password.py migrate --from-file users.json --dry-run

`migrate` copies a local users.json into the configured GITHUB_DATA_REPO —
use it once when moving off the public repo.
"""
import argparse
import getpass
import json
import os
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fail(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _store():
    from gh_api import gh_read, gh_write, resolve_repo
    return gh_read, gh_write, resolve_repo


def _load():
    gh_read, _, resolve_repo = _store()
    res = gh_read("users.json", data=True)
    if res.broken or res.unconfigured:
        _fail(f"cannot read the account store: {res.describe()}\n"
              f"       check GH_PAT and GITHUB_DATA_REPO, then run: python preflight.py")
    users = res.content if res.ok else {}
    if not isinstance(users, dict):
        _fail("users.json is not a JSON object")
    return users, res.sha, resolve_repo(data=True)


def _suggest_password(n=16):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def cmd_list(args):
    users, _, repo = _load()
    print(f"account store: {repo}  ({len(users)} accounts)\n")
    for name, u in sorted(users.items()):
        print(f"  {name:<16} {u.get('email',''):<32} reports={u.get('report_count', 0)}")


def cmd_reset(args):
    import bcrypt
    _, gh_write, repo = _store()
    users, sha, repo = _load()

    if args.username not in users:
        _fail(f"no such account: {args.username}\n"
              f"       known: {', '.join(sorted(users)) or '(none)'}")

    pw = args.password
    if not pw:
        if args.generate:
            pw = _suggest_password()
            print(f"generated password: {pw}\n(save this — it is not stored anywhere in plaintext)")
        else:
            pw = getpass.getpass(f"New password for {args.username}: ")
            if pw != getpass.getpass("Confirm: "):
                _fail("passwords do not match")
    if len(pw) < 6:
        _fail("password must be at least 6 characters")

    users[args.username]["password_hash"] = bcrypt.hashpw(
        pw.encode(), bcrypt.gensalt()).decode()

    if args.dry_run:
        print(f"[dry-run] would update {args.username} in {repo}")
        return

    res = gh_write("users.json", users, sha,
                   message=f"admin: reset password for {args.username}", data=True)
    if not res.ok:
        _fail(f"write failed: {res.describe()}")
    print(f"password updated for {args.username} in {repo}")


def cmd_migrate(args):
    _, gh_write, _ = _store()
    src = Path(args.from_file)
    if not src.exists():
        _fail(f"{src} not found")
    incoming = json.loads(src.read_text())
    if not isinstance(incoming, dict):
        _fail(f"{src} is not a JSON object")

    existing, sha, repo = _load()
    merged = dict(existing)
    added, skipped = [], []
    for name, rec in incoming.items():
        if name in merged:
            skipped.append(name)
        else:
            merged[name] = rec
            added.append(name)

    print(f"target: {repo}")
    print(f"  existing: {len(existing)}   incoming: {len(incoming)}")
    print(f"  would add:  {', '.join(added) or '(none)'}")
    print(f"  would skip: {', '.join(skipped) or '(none)'}  (already present)")

    if args.dry_run:
        print("\n[dry-run] nothing written")
        return
    if not added:
        print("\nnothing to do")
        return

    res = gh_write("users.json", merged, sha,
                   message="admin: migrate accounts to private data repo", data=True)
    if not res.ok:
        _fail(f"write failed: {res.describe()}")
    print(f"\nmigrated {len(added)} accounts into {repo}")
    print("Now reset every migrated password — the old hashes were public:")
    for n in added:
        print(f"  python scripts/reset_password.py reset {n} --generate")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list accounts in the configured store")

    r = sub.add_parser("reset", help="set a new password for one account")
    r.add_argument("username")
    r.add_argument("--password", help="new password (omit to be prompted)")
    r.add_argument("--generate", action="store_true", help="generate a strong password")
    r.add_argument("--dry-run", action="store_true")

    m = sub.add_parser("migrate", help="copy a local users.json into the private data repo")
    m.add_argument("--from-file", default="users.json")
    m.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    {"list": cmd_list, "reset": cmd_reset, "migrate": cmd_migrate}[args.cmd](args)


if __name__ == "__main__":
    main()
