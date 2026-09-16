#!/usr/bin/env python3
"""
Helper script to get Spotify access token using OAuth flow.
This is needed to authenticate the export script.
"""

import html
import http.server
import os
import secrets
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

from spotify_config import (
    ENV_PATH,
    REDIRECT_HOST,
    REDIRECT_PORT,
    REDIRECT_URI,
    SCOPES,
    request_token,
    write_env,
)

# Spotify App Credentials
# Create your app at: https://developer.spotify.com/dashboard
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# How long to wait for the user to authorize in the browser
AUTH_TIMEOUT_SECONDS = 120

# Cap on the error text echoed to the terminal
MAX_ERROR_CHARS = 100


def sanitize_for_terminal(text: str) -> str:
    """Drop non-printable characters from text that reaches the terminal.

    The reason is echoed to stdout, and anything arriving on the callback is
    untrusted - escape sequences must not reach the TTY.
    """
    cleaned = "".join(c for c in text if c.isprintable())[:MAX_ERROR_CHARS]
    return cleaned or "unspecified error"


class CallbackServer(http.server.HTTPServer):
    """Serves the OAuth callback and holds its outcome.

    An authorization ends with exactly one of: a code, an authentic failure,
    or neither (only unsolicited callbacks arrived, and we timed out).
    """

    def __init__(self, address, expected_state: str):
        super().__init__(address, CallbackHandler)
        self.expected_state = expected_state
        self.auth_code = None
        self.auth_error = None
        self.ignored = 0


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handle OAuth callback."""

    def _respond(self, status: int, body: str):
        """Send a minimal HTML response."""
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _rejection_reason(self, params: dict):
        """Why an authentic callback can't be used, or None if it's good."""
        if "error" in params:
            return sanitize_for_terminal(params["error"][0])
        if "code" not in params:
            return "no authorization code in callback"
        return None

    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed = urlparse(self.path)

        # Ignore anything that isn't the callback (favicon requests, probes)
        # so a stray hit can't end the flow early.
        if parsed.path != "/callback":
            self._respond(404, "<h1>Not Found</h1>")
            return

        params = parse_qs(parsed.query)

        # Everything below this point trusts the query, so the state is checked
        # first and nothing else is read until it matches. A callback that
        # fails it is unsolicited: refuse it without recording an outcome, so
        # it can neither end the flow nor put its own text on our terminal.
        # Spotify returns the state on error responses too, so an `error` that
        # skipped this check would be just as forgeable.
        if params.get("state", [None])[0] != self.server.expected_state:
            self.server.ignored += 1
            self._respond(400, "<h1>Authorization Failed</h1><p>Unexpected.</p>")
            return

        reason = self._rejection_reason(params)

        if reason:
            self.server.auth_error = reason
            self._respond(
                400, f"<h1>Authorization Failed</h1><p>{html.escape(reason)}</p>"
            )
            return

        self.server.auth_code = params["code"][0]
        self._respond(
            200,
            "<html><head><title>Spotify Auth Success</title></head><body>"
            "<h1>Authorization Successful!</h1>"
            "<p>You can close this window and return to the terminal.</p>"
            "</body></html>",
        )

    def log_message(self, format, *args):
        """Suppress server logs."""
        pass


def get_authorization_url(state: str) -> str:
    """Generate Spotify authorization URL."""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "show_dialog": "true",
    }

    return f"https://accounts.spotify.com/authorize?{urlencode(params)}"


def wait_for_callback(httpd, timeout: int = AUTH_TIMEOUT_SECONDS):
    """Serve requests until the callback arrives, or record why it didn't."""
    # handle_request() blocks in select() until a connection arrives or the
    # poll interval elapses, so waiting costs nothing. The deadline is
    # wall-clock, so serving stray requests doesn't eat into the time the
    # user has to authorize.
    httpd.timeout = 5  # how often the deadline is rechecked
    deadline = time.monotonic() + timeout

    while httpd.auth_code is None and httpd.auth_error is None:
        if time.monotonic() >= deadline:
            httpd.auth_error = "timed out waiting for authorization"
            return
        httpd.handle_request()


def main():
    """Main OAuth flow."""
    print("=" * 60)
    print("SPOTIFY TOKEN GENERATOR")
    print("=" * 60)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("\nERROR: Missing Spotify app credentials")
        print("\nTo get your credentials:")
        print("1. Go to https://developer.spotify.com/dashboard")
        print("2. Create a new app (or use existing)")
        print(f"3. Add '{REDIRECT_URI}' to Redirect URIs")
        print("4. Copy .env.example to .env")
        print("5. Fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET, then re-run")
        return

    print(f"\nRedirect URI (must match your app's settings exactly):\n  {REDIRECT_URI}")
    print(f"\nRequesting scopes: {', '.join(SCOPES)}")
    print("\nStep 1: Opening browser for Spotify authorization...")
    print("Step 2: Log in and authorize the app")
    print(f"Step 3: You'll be redirected back to {REDIRECT_HOST}:{REDIRECT_PORT}")

    state = secrets.token_urlsafe(32)

    # Bind to loopback only - the redirect never comes from off-machine, and
    # binding every interface would expose the callback to the local network.
    with CallbackServer((REDIRECT_HOST, REDIRECT_PORT), state) as httpd:
        auth_url = get_authorization_url(state)
        print(f"\nIf the browser doesn't open, visit:\n{auth_url}\n")
        webbrowser.open(auth_url)

        wait_for_callback(httpd)

        if httpd.ignored:
            print(
                f"\n⚠ Ignored {httpd.ignored} callback(s) that did not match "
                "this session's state"
            )

        if httpd.auth_error:
            print(f"\nERROR: {httpd.auth_error}")
            print("Please try again")
            return

        auth_code = httpd.auth_code

    print("\n✓ Authorization code received")
    print("Exchanging code for access token...")

    token_data = request_token(
        CLIENT_ID,
        CLIENT_SECRET,
        {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
    )

    if not token_data:
        print("\nERROR: Failed to get access token")
        return

    expires_in = token_data.get("expires_in", 0)

    write_env(
        SPOTIFY_ACCESS_TOKEN=token_data["access_token"],
        SPOTIFY_REFRESH_TOKEN=token_data["refresh_token"],
        SPOTIFY_CLIENT_ID=CLIENT_ID,
        SPOTIFY_CLIENT_SECRET=CLIENT_SECRET,
    )

    print(f"\n✓ Access token obtained (expires in {expires_in / 3600:.1f} hours)")
    print(f"✓ Credentials saved to {ENV_PATH}")
    print("\nYou can now run: uv run spotify_export.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
    except OSError as e:
        print(f"\nError: {e}")
        print(f"\nIs port {REDIRECT_PORT} already in use? Set SPOTIFY_REDIRECT_PORT")
        print("in .env and add the matching Redirect URI in the Spotify dashboard.")
    except Exception as e:
        print(f"\nError: {e}")
