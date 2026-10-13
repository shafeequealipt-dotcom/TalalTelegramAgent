"""One-time Google Business Profile OAuth bootstrap (run manually, NOT by the agent).

Run it on your Mac (it needs a browser), with the OAuth client credentials
exported in your shell (~/.zshrc):
    TALAL_GBP_ClientID, TALAL_GBP_ClientSecret

  1) python3 -m agent.gbp_auth login
       Opens a Google consent URL; sign in with the Google account that
       owns/manages the clinic's Business Profile and approve. The redirect is
       captured automatically on http://localhost:8765 (if that port can't be
       bound, e.g. headless, you paste the `code=` value from the address bar).
       Prints the TALAL_GBP_RefreshToken line to add to ~/.zshrc.

  2) python3 -m agent.gbp_auth discover
       (needs TALAL_GBP_RefreshToken exported) Lists your accounts/locations and
       prints the TALAL_GBP_AccountID / TALAL_GBP_LocationID lines to add.

Standalone on purpose — reads only TALAL_GBP_* from the environment, so it works
on a machine that doesn't have the Cloudflare/GitHub vars or REPO_DIR set.
"""
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

SCOPE = "https://www.googleapis.com/auth/business.manage"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PORT = 8765
REDIRECT = f"http://localhost:{PORT}"
ACCT_MGMT = "https://mybusinessaccountmanagement.googleapis.com/v1"
BIZ_INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"


def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


CLIENT_ID = _env("TALAL_GBP_ClientID", "GBP_CLIENT_ID")
CLIENT_SECRET = _env("TALAL_GBP_ClientSecret", "GBP_CLIENT_SECRET")
REFRESH_TOKEN = _env("TALAL_GBP_RefreshToken", "GBP_REFRESH_TOKEN")


def _require(*pairs):
    missing = [n for n, v in pairs if not v]
    if missing:
        sys.exit(f"Missing from the environment: {', '.join(missing)}")


def _capture_code(expected_state: str, timeout: int = 300):
    """Wait for Google's redirect on localhost and return its `code`. Returns None
    if the port can't be bound or nothing arrives in time (caller falls back to
    a manual paste)."""
    holder = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                holder["code"] = (q.get("code") or [None])[0]
                holder["error"] = (q.get("error") or [None])[0]
                holder["state"] = (q.get("state") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h3>Authorised. You can close this tab and "
                             b"return to the terminal.</h3>")

        def log_message(self, *args):
            pass

    try:
        srv = HTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return None
    srv.timeout = 5
    deadline = time.time() + timeout
    while time.time() < deadline and "code" not in holder and "error" not in holder:
        srv.handle_request()
    srv.server_close()
    if holder.get("error"):
        sys.exit(f"Google returned an error: {holder['error']}")
    if holder.get("code") and holder.get("state") != expected_state:
        sys.exit("OAuth state mismatch — aborting (possible forged redirect).")
    return holder.get("code")


def login():
    _require(("TALAL_GBP_ClientID", CLIENT_ID),
             ("TALAL_GBP_ClientSecret", CLIENT_SECRET))
    state = secrets.token_urlsafe(16)
    params = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",     # -> refresh token
        "prompt": "consent",          # force a refresh token even on re-consent
        "state": state,
    })
    url = f"{AUTH_URL}?{params}"
    print("\nOpen this URL and approve with the Google account that owns/manages")
    print("the clinic's Business Profile:\n")
    print(f"   {url}\n")
    print("(If you see 'Google hasn't verified this app', click Advanced -> "
          "Go to <app> (unsafe) — it's your own app.)\n")
    try:
        webbrowser.open(url)
    except Exception:  # noqa
        pass
    print(f"Waiting for the redirect on {REDIRECT} (up to 5 min)...")
    code = _capture_code(state)
    if not code:
        print("\nCouldn't capture the redirect automatically. After approving, the "
              "browser lands on a localhost URL that won't load — copy the value of "
              "its `code=` parameter.")
        code = input("Paste the code here: ").strip()
    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": urllib.parse.unquote(code),
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Token exchange failed {e.code}: {e.read().decode(errors='replace')[:300]}")
    rt = tok.get("refresh_token")
    if not rt:
        sys.exit(f"No refresh_token in the response (keys: {list(tok)}). Re-run; the "
                 "consent screen must appear (prompt=consent).")
    print("\nAdd this line to ~/.zshrc (then `source ~/.zshrc`):\n")
    print(f'export TALAL_GBP_RefreshToken="{rt}"\n')


def _access_token() -> str:
    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def _get(url):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {_access_token()}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        hint = ""
        if e.code == 429:
            hint = (" — quota is 0 until Google approves your GBP API access "
                    "request (see SETUP.md, Google Business Profile).")
        sys.exit(f"GET {url} -> {e.code}: {detail}{hint}")


def discover():
    _require(("TALAL_GBP_ClientID", CLIENT_ID),
             ("TALAL_GBP_ClientSecret", CLIENT_SECRET),
             ("TALAL_GBP_RefreshToken", REFRESH_TOKEN))
    accts = _get(ACCT_MGMT + "/accounts").get("accounts", [])
    if not accts:
        sys.exit("No Business Profile accounts visible to this Google account.")
    for a in accts:
        aid = a["name"].split("/")[-1]
        print(f"\nAccount: {a.get('accountName', '?')}  ->  TALAL_GBP_AccountID={aid}")
        locs = _get(f"{BIZ_INFO}/accounts/{aid}/locations"
                    "?readMask=name,title,storefrontAddress").get("locations", [])
        for l in locs:
            lid = l["name"].split("/")[-1]
            print(f"  Location: {l.get('title', '?')}  ->  TALAL_GBP_LocationID={lid}")
    print("\nAdd the matching TALAL_GBP_AccountID and TALAL_GBP_LocationID exports "
          "to ~/.zshrc.\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        login()
    elif cmd == "discover":
        discover()
    else:
        print(__doc__)
