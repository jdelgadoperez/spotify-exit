"""Tests for the OAuth callback server and the shared .env writer."""

import http.server
import threading
import urllib.error
import urllib.request

import pytest

import get_token
import spotify_config


@pytest.fixture
def callback_server():
    """An OAuth callback server on an ephemeral port, served in a thread."""
    started = []

    def start(timeout=10):
        httpd = http.server.HTTPServer(
            (spotify_config.REDIRECT_HOST, 0), get_token.CallbackHandler
        )
        httpd.auth_code = None
        httpd.auth_error = None
        httpd.expected_state = "test-state"

        thread = threading.Thread(
            target=get_token.wait_for_callback, args=(httpd, timeout), daemon=True
        )
        thread.start()
        started.append((httpd, thread))
        return httpd, httpd.server_address[1]

    yield start

    for httpd, thread in started:
        thread.join(timeout=5)
        assert not thread.is_alive(), "callback server thread did not exit"
        httpd.server_close()


def fetch(url):
    """GET a URL, returning (status, body) even for error responses."""
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_callback_captures_authorization_code(callback_server):
    httpd, port = callback_server()

    status, _ = fetch(f"http://127.0.0.1:{port}/callback?code=abc123&state=test-state")

    assert status == 200
    assert httpd.auth_code == "abc123"
    assert httpd.auth_error is None


def test_stray_request_does_not_end_the_flow(callback_server):
    """A browser favicon hit used to consume the single handled request."""
    httpd, port = callback_server()

    assert fetch(f"http://127.0.0.1:{port}/favicon.ico")[0] == 404
    assert fetch(f"http://127.0.0.1:{port}/robots.txt")[0] == 404
    fetch(f"http://127.0.0.1:{port}/callback?code=late&state=test-state")

    assert httpd.auth_code == "late"


@pytest.mark.parametrize(
    "query,expected_reason",
    [
        ("code=abc&state=wrong-state", "state mismatch"),
        ("error=access_denied&state=test-state", "access_denied"),
        ("state=test-state", "no authorization code in callback"),
    ],
)
def test_rejections_report_their_own_reason(callback_server, query, expected_reason):
    httpd, port = callback_server()

    status, _ = fetch(f"http://127.0.0.1:{port}/callback?{query}")

    assert status == 400
    assert httpd.auth_code is None
    assert httpd.auth_error == expected_reason


def test_timeout_reports_through_the_same_error_channel(callback_server):
    httpd, _ = callback_server(timeout=0)

    assert httpd.auth_error == "timed out waiting for authorization"


def test_error_reason_is_escaped_not_reflected_raw(callback_server):
    """The reason comes from the query string, so it must not be injectable."""
    _, port = callback_server()

    _, body = fetch(
        f"http://127.0.0.1:{port}/callback"
        "?error=%3Cscript%3Ealert(1)%3C/script%3E&state=test-state"
    )

    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_redirect_uri_uses_loopback_ip_not_localhost():
    """Spotify rejects `localhost` as a redirect URI host."""
    assert spotify_config.REDIRECT_HOST == "127.0.0.1"
    assert spotify_config.REDIRECT_URI == (
        f"http://127.0.0.1:{spotify_config.REDIRECT_PORT}/callback"
    )


def test_authorization_url_carries_state_and_scopes():
    url = get_token.get_authorization_url("some-state")

    assert "state=some-state" in url
    for scope in spotify_config.SCOPES:
        assert scope in url


def test_write_env_preserves_unrelated_keys_and_comments(tmp_path, monkeypatch):
    """get_token.py used to truncate .env, destroying any other variables."""
    env = tmp_path / ".env"
    env.write_text('# keep this note\nUNRELATED="keepme"\nSPOTIFY_ACCESS_TOKEN="old"\n')
    monkeypatch.setattr(spotify_config, "ENV_PATH", env)

    spotify_config.write_env(SPOTIFY_ACCESS_TOKEN="new", SPOTIFY_REFRESH_TOKEN="rt")

    contents = env.read_text()
    assert "# keep this note" in contents
    assert "keepme" in contents
    assert "new" in contents
    assert "rt" in contents
    assert "old" not in contents


def test_write_env_creates_the_file_when_absent(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(spotify_config, "ENV_PATH", env)

    spotify_config.write_env(SPOTIFY_ACCESS_TOKEN="fresh")

    assert env.exists()
    assert "fresh" in env.read_text()
