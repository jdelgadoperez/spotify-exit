#!/usr/bin/env python3
"""
Helper script to get Spotify access token using OAuth flow.
This is needed to authenticate the export script.
"""

import os
import webbrowser
from urllib.parse import urlencode
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Spotify App Credentials
# Create your app at: https://developer.spotify.com/dashboard
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8888/callback"

# Required scopes for full data export
SCOPES = [
    "user-library-read",
    "user-follow-read",
    "user-top-read",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-read-email",
    "user-read-private",
]


class CallbackHandler(http.server.SimpleHTTPRequestHandler):
    """Handle OAuth callback."""

    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed = urlparse(self.path)

        if parsed.path == "/callback":
            params = parse_qs(parsed.query)

            if "code" in params:
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()

                html = """
                <html>
                <head><title>Spotify Auth Success</title></head>
                <body>
                    <h1>Authorization Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode())

                # Store the code for exchange
                self.server.auth_code = params["code"][0]
            else:
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Authorization Failed</h1>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress server logs."""
        pass


def get_authorization_url():
    """Generate Spotify authorization URL."""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "show_dialog": "true",
    }

    auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"
    return auth_url


def exchange_code_for_token(auth_code):
    """Exchange authorization code for access token."""
    import requests
    import base64

    # Encode credentials
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
    }

    response = requests.post(
        "https://accounts.spotify.com/api/token", headers=headers, data=data
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error exchanging code: {response.text}")
        return None


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
        print("3. Add 'http://localhost:8888/callback' to Redirect URIs")
        print("4. Copy Client ID and Client Secret")
        print("5. Set environment variables or update this script:")
        print("   export SPOTIFY_CLIENT_ID='your_client_id'")
        print("   export SPOTIFY_CLIENT_SECRET='your_client_secret'")
        return

    print("\nStep 1: Opening browser for Spotify authorization...")
    print("Step 2: Log in and authorize the app")
    print("Step 3: You'll be redirected to localhost (this script)")
    print("\nStarting local server on port 8888...")

    # Start local server to receive callback
    with socketserver.TCPServer(("", 8888), CallbackHandler) as httpd:
        httpd.auth_code = None

        # Open browser for authorization
        auth_url = get_authorization_url()
        webbrowser.open(auth_url)

        # Wait for callback (with timeout)
        httpd.timeout = 120  # 2 minute timeout
        httpd.handle_request()

        if not httpd.auth_code:
            print("\nERROR: No authorization code received")
            print("Please try again")
            return

        print("\n✓ Authorization code received")
        print("Exchanging code for access token...")

        # Exchange code for token
        token_data = exchange_code_for_token(httpd.auth_code)

        if token_data:
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in")

            print("\n" + "=" * 60)
            print("SUCCESS! Your access token:")
            print("=" * 60)
            print(f"\n{access_token}\n")
            print("=" * 60)
            print(
                f"\nToken expires in: {expires_in} seconds ({expires_in/3600:.1f} hours)"
            )
            print(f"Refresh token: {refresh_token}")

            # Save to .env file
            env_path = ".env"
            with open(env_path, "w") as f:
                f.write(f"SPOTIFY_ACCESS_TOKEN={access_token}\n")
                f.write(f"SPOTIFY_REFRESH_TOKEN={refresh_token}\n")
                f.write(f"SPOTIFY_CLIENT_ID={CLIENT_ID}\n")
                f.write(f"SPOTIFY_CLIENT_SECRET={CLIENT_SECRET}\n")

            print(f"\n✓ Credentials saved to {env_path}")
            print("\nYou can now run: python spotify_export.py")
        else:
            print("\nERROR: Failed to get access token")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
    except Exception as e:
        print(f"\nError: {e}")
