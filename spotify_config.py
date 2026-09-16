"""Shared configuration and Spotify auth helpers.

Both `get_token.py` and `spotify_export.py` read their credentials from the
same `.env` and talk to the same token endpoint, so the redirect URI, the
scopes and the token request live here rather than being restated in each.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

# Anchor .env to this file rather than the working directory, so the export
# script updates the same file the token generator wrote.
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

TOKEN_URL = "https://accounts.spotify.com/api/token"

# Spotify requires an explicit loopback IP here - the hostname "localhost" is
# rejected as a redirect URI. The dashboard may display 127.0.0.1 back as
# "localhost" after a refresh; the value is still stored correctly.
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = int(os.getenv("SPOTIFY_REDIRECT_PORT", "8888"))
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"

# The authoritative scope list - the README describes these, but this is what
# is actually requested.
SCOPES = [
    "user-library-read",
    "user-follow-read",
    "user-top-read",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-read-email",
    "user-read-private",
]


def write_env(**values: str):
    """Update keys in .env, leaving every other key and comment untouched."""
    for key, value in values.items():
        set_key(ENV_PATH, key, value)


def request_token(client_id: str, client_secret: str, payload: dict):
    """POST to Spotify's token endpoint. Returns the JSON body, or None."""
    try:
        response = requests.post(
            TOKEN_URL, auth=(client_id, client_secret), data=payload, timeout=30
        )
    except requests.exceptions.RequestException as e:
        print(f"ERROR contacting Spotify token endpoint: {e}")
        return None

    if response.status_code == 200:
        return response.json()

    print(f"ERROR from Spotify token endpoint ({response.status_code}): {response.text}")
    return None
