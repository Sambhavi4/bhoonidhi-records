#!/usr/bin/env python3
"""bhoonidhi_login.py - authenticate against Bhoonidhi, once, and cache it.

WHY THIS EXISTS

Bhoonidhi's API is session-based and gates everything behind a token. Hitting
any data endpoint without one gives you exactly this, which is the error most
people meet first:

    GET https://bhoonidhi-api.nrsc.gov.in/download
    {"ErrorCode":"401","Description":"UNAUTHORIZED",
     "Action":"Invalid session detected! Please login again."}

That is correct behaviour on NRSC's part and this project does not complain
about it (the gap identified in docs/GAP_ANALYSIS.md is about computation, not
access). But it makes the login step the first thing that can go wrong, and
three things made it harder than it needed to be:

  1. every harvest logged in afresh, and Bhoonidhi limits concurrent
     sessions - so repeated runs eventually get HTTP 403 and you are locked
     out until the old sessions expire;
  2. there was no way to test credentials without running a whole harvest;
  3. the client reported bare status codes, while the genuinely useful text
     is in Bhoonidhi's own "Action" field.

This script fixes all three: one login, cached token reused by
fetch_footprints.py, a real logout to release the session, and errors that
quote Bhoonidhi back at you.

USAGE
    make login                      # or: ./scripts/bhoonidhi_login.py
    ./scripts/bhoonidhi_login.py --status
    ./scripts/bhoonidhi_login.py --logout

SECURITY
    The password is read from the environment or .env, never from argv (which
    is world-readable in /proc). It is never printed. The cached token is
    written 0600 under ../runtime/ and is gitignored. No credential is ever
    sent anywhere except bhoonidhi-api.nrsc.gov.in over HTTPS.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests is required - run: make install")

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path(os.environ.get("RUNTIME", ROOT.parent / "runtime"))
TOKEN_FILE = RUNTIME / "bhoonidhi-token.json"
API = os.environ.get("BHOONIDHI_API", "https://bhoonidhi-api.nrsc.gov.in")
UA = "bhoonidhi-records/1.0 (CyberGIS course project; +contact via repository)"

# Bhoonidhi tokens are not accompanied by a documented lifetime, so assume a
# conservative one and re-authenticate rather than fail mid-harvest.
ASSUMED_TTL = timedelta(minutes=50)


def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


ok = lambda m: print(f"   {c('32', ' ok ')}  {m}")
bad = lambda m: print(f"   {c('31', 'fail')}  {m}")
info = lambda m: print(f"   ..    {m}")


def load_dotenv() -> None:
    """Read .env without a dependency. Existing env vars win."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def explain(r: requests.Response) -> str:
    """Bhoonidhi's useful message lives in the body, not the status line."""
    try:
        d = r.json()
        parts = [d.get("Description"), d.get("Action")]
        msg = " - ".join(p for p in parts if p)
        return msg or r.text[:200]
    except ValueError:
        return r.text[:200] or f"HTTP {r.status_code}"


def read_cached() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        d = json.loads(TOKEN_FILE.read_text())
        exp = datetime.fromisoformat(d["expires_utc"])
        if exp <= datetime.now(timezone.utc):
            return None
        return d
    except (ValueError, KeyError, OSError):
        return None


def write_cached(token: str, user: str) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({
        "access_token": token,
        "user": user,
        "obtained_utc": datetime.now(timezone.utc).isoformat(),
        "expires_utc": (datetime.now(timezone.utc) + ASSUMED_TTL).isoformat(),
        "note": "cached by scripts/bhoonidhi_login.py; delete to force re-login",
    }, indent=2) + "\n")
    TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def login(force: bool = False) -> str:
    """Return a usable token, from cache when possible."""
    if not force:
        cached = read_cached()
        if cached:
            ok(f"reusing cached session for {cached['user']} "
               f"(expires {cached['expires_utc'][:19]}Z)")
            return cached["access_token"]

    user, pw = os.environ.get("BHOONIDHI_USER"), os.environ.get("BHOONIDHI_PASS")
    if not user or not pw:
        bad("BHOONIDHI_USER / BHOONIDHI_PASS are not set")
        print("\n   Register free at https://bhoonidhi.nrsc.gov.in/ then:")
        print("       cp .env.example .env     # fill in user id and password")
        print("       make login")
        print("\n   Or skip Bhoonidhi entirely - the service runs on the public")
        print("   substitute with no credentials at all:")
        print("       make footprints")
        sys.exit(2)

    info(f"authenticating as {user} at {API}")
    s = requests.Session()
    s.headers["User-Agent"] = UA
    try:
        r = s.post(f"{API}/auth/token",
                   json={"userId": user, "password": pw,
                         "grant_type": "password"}, timeout=60)
    except requests.RequestException as e:
        bad(f"could not reach {API}: {e}")
        print("\n   NRSC hosts have been intermittently unreachable. The rest of")
        print("   this project works offline; see docs/GAP_ANALYSIS.md.")
        sys.exit(1)

    if r.status_code == 400:
        bad(f"Bhoonidhi rejected the request: {explain(r)}")
        print("\n   BHOONIDHI_USER must be the user id chosen at registration,")
        print("   which is not always your email address.")
        sys.exit(1)
    if r.status_code == 401:
        bad(f"credentials rejected: {explain(r)}")
        print("\n   Check them by signing in at https://bhoonidhi.nrsc.gov.in/")
        sys.exit(1)
    if r.status_code == 403:
        bad(f"too many active sessions: {explain(r)}")
        print("\n   Bhoonidhi limits concurrent sessions. Either:")
        print("       ./scripts/bhoonidhi_login.py --logout   # release this one")
        print("   or sign out in the browser, or wait for the old session to")
        print("   expire. Caching (this script) is what stops you hitting this.")
        sys.exit(1)
    if not r.ok:
        bad(f"HTTP {r.status_code}: {explain(r)}")
        sys.exit(1)

    try:
        token = r.json()["access_token"]
    except (ValueError, KeyError):
        bad("login returned 200 but no access_token; response shape changed")
        print(f"   body: {r.text[:300]}")
        sys.exit(1)

    write_cached(token, user)
    ok(f"authenticated as {user}")
    ok(f"token cached 0600 at {TOKEN_FILE}")
    return token


def verify(token: str) -> bool:
    """Prove the token actually opens a data endpoint, not just that it parsed."""
    info("verifying the token against /data/collections")
    try:
        r = requests.get(f"{API}/data/collections",
                         headers={"Authorization": f"Bearer {token}",
                                  "User-Agent": UA}, timeout=60)
    except requests.RequestException as e:
        bad(f"verification request failed: {e}")
        return False
    if r.status_code == 401:
        bad(f"token not accepted: {explain(r)}")
        return False
    if not r.ok:
        bad(f"HTTP {r.status_code}: {explain(r)}")
        return False
    try:
        d = r.json()
        n = len(d if isinstance(d, list) else d.get("collections", d))
        ok(f"token works - /data/collections returned {n} entries")
    except ValueError:
        ok("token works - /data/collections returned 200")
    return True


def logout() -> int:
    cached = read_cached()
    if not cached:
        info("no cached session to release")
        TOKEN_FILE.unlink(missing_ok=True)
        return 0
    try:
        r = requests.post(f"{API}/auth/logout",
                          headers={"Authorization": f"Bearer {cached['access_token']}",
                                   "User-Agent": UA}, timeout=60)
        ok(f"logout returned HTTP {r.status_code}") if r.ok else \
            info(f"logout returned HTTP {r.status_code}: {explain(r)}")
    except requests.RequestException as e:
        info(f"logout request failed ({e}); clearing the local cache anyway")
    TOKEN_FILE.unlink(missing_ok=True)
    ok("local token cache cleared")
    return 0


def status() -> int:
    cached = read_cached()
    if cached:
        ok(f"cached session for {cached['user']}, "
           f"expires {cached['expires_utc'][:19]}Z")
        return 0
    if TOKEN_FILE.exists():
        info("a cached token exists but has expired; `make login` will renew it")
    else:
        info("no cached session")
    u = os.environ.get("BHOONIDHI_USER")
    info(f"BHOONIDHI_USER is {'set (' + u + ')' if u else 'NOT set'}")
    info(f"BHOONIDHI_PASS is {'set' if os.environ.get('BHOONIDHI_PASS') else 'NOT set'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show the cached session")
    ap.add_argument("--logout", action="store_true", help="release the session")
    ap.add_argument("--force", action="store_true", help="ignore the cache")
    a = ap.parse_args()

    load_dotenv()
    print("\n\033[1m-- Bhoonidhi login\033[0m")
    if a.status:
        return status()
    if a.logout:
        return logout()

    token = login(force=a.force)
    if not verify(token):
        print("\n   The cached token did not work. Retrying with a fresh login:")
        TOKEN_FILE.unlink(missing_ok=True)
        token = login(force=True)
        if not verify(token):
            return 1

    print(f"""
\033[1mlogged in\033[0m
  Harvest real Bhoonidhi footprints now:
    ./scripts/fetch_footprints.py --source bhoonidhi --collection <collection_id>

  Collection ids come from this project's own catalogue:
    curl 'http://localhost:5003/collections/bhoonidhi/items?limit=59&f=json' \\
      | grep -o '"id": "[^"]*"'

  Release the session when done:
    ./scripts/bhoonidhi_login.py --logout
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
