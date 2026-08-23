"""Bootstraps SERA's GitHub App registration using GitHub's "manifest
flow" -- the most automated path available. GitHub's security model
requires a human, logged into the target GitHub account, to click
"Create GitHub App" in their browser; nothing can substitute for that
click (and nothing should -- that's the point of App installation being
opt-in and auditable). Everything else here is automatic.

What this script does:
  1. Starts a tiny local HTTP server to catch GitHub's redirect.
  2. Opens your browser to a GitHub page pre-filled with SERA's manifest
     (permissions, webhook URL, events) -- you review and click "Create
     GitHub App".
  3. GitHub redirects back with a one-time code; this script exchanges it
     for the App's id, private key, webhook secret, and slug automatically.
  4. Writes them to `.env.github_app` (gitignored) for you to load.

Usage:
    python scripts/register_github_app.py --webhook-url https://your-tunnel/webhooks/github

For local development, the webhook URL needs to be a publicly reachable
address that proxies to your machine -- smee.io (https://smee.io/new,
click "Start a new channel", use the URL it gives you) is the standard,
zero-signup way to do this for a GitHub App in development. A production
deployment would use its real public URL instead.
"""
from __future__ import annotations

import argparse
import http.server
import json
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_OUTPUT_PATH = REPO_ROOT / ".env.github_app"
CALLBACK_PORT = 8788

_received_code: dict = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(self.path).query)
        code = query.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if code:
            _received_code["code"] = code
            self.wfile.write(b"<h2>SERA GitHub App created.</h2><p>You can close this tab.</p>")
        else:
            self.wfile.write(b"<h2>No code received.</h2><p>Something went wrong -- check the terminal.</p>")

    def log_message(self, format, *args):  # noqa: A002 -- silence default request logging
        pass


def build_manifest(app_name: str, webhook_url: str, redirect_url: str) -> dict:
    return {
        "name": app_name,
        "url": "https://github.com/",  # your app's homepage; update after you have a real one
        "hook_attributes": {"url": webhook_url},
        "redirect_url": redirect_url,
        "public": False,
        "default_permissions": {
            "contents": "read",
            "pull_requests": "write",
            "metadata": "read",
        },
        "default_events": ["installation", "installation_repositories", "pull_request"],
    }


def write_manifest_form_html(manifest: dict, state: str, out_path: Path) -> None:
    """GitHub's manifest flow requires a POST with a `manifest` form field
    -- not something you can express as a plain link -- so we write a
    tiny auto-submitting HTML page and open that instead.
    """
    manifest_json = json.dumps(manifest)
    html = f"""<!doctype html>
<html><body onload="document.forms[0].submit()">
<form action="https://github.com/settings/apps/new?state={state}" method="post">
  <input type="hidden" name="manifest" value='{manifest_json}'>
  <p>Redirecting to GitHub to create the SERA GitHub App...</p>
  <button type="submit">Click here if not redirected automatically</button>
</form>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")


def exchange_code_for_credentials(code: str) -> dict:
    resp = requests.post(
        f"https://api.github.com/app-manifests/{code}/conversions",
        headers={"Accept": "application/vnd.github+json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", type=str, default=f"SERA-{secrets.token_hex(3)}")
    parser.add_argument(
        "--webhook-url",
        type=str,
        required=True,
        help="publicly reachable URL for installation/PR webhooks (e.g. a smee.io channel)",
    )
    args = parser.parse_args()

    redirect_url = f"http://localhost:{CALLBACK_PORT}/callback"
    state = secrets.token_urlsafe(16)
    manifest = build_manifest(args.name, args.webhook_url, redirect_url)

    form_path = REPO_ROOT / "_github_app_manifest_form.html"
    write_manifest_form_html(manifest, state, form_path)

    server = http.server.HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f"opening your browser to create the GitHub App {args.name!r}...")
    print("review the permissions GitHub shows you, then click 'Create GitHub App'.")
    webbrowser.open(form_path.as_uri())

    print(f"waiting for the redirect on {redirect_url} ...")
    while "code" not in _received_code:
        threading.Event().wait(0.5)
    server.shutdown()
    form_path.unlink(missing_ok=True)

    print("exchanging the one-time code for App credentials...")
    creds = exchange_code_for_credentials(_received_code["code"])

    env_lines = [
        f"GITHUB_APP_ID={creds['id']}",
        f"GITHUB_APP_SLUG={creds['slug']}",
        f"GITHUB_WEBHOOK_SECRET={creds['webhook_secret']}",
        "GITHUB_APP_PRIVATE_KEY<<'EOF'",
        creds["pem"].strip(),
        "EOF",
    ]
    ENV_OUTPUT_PATH.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    print(f"\nDone. App credentials written to {ENV_OUTPUT_PATH} (gitignored).")
    print(f"App slug: {creds['slug']}  |  install URL: https://github.com/apps/{creds['slug']}/installations/new")
    print(
        "\nGITHUB_APP_PRIVATE_KEY is multi-line PEM -- load it with your shell's process "
        "substitution or a dotenv tool that supports multi-line values, not a plain `export`."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
