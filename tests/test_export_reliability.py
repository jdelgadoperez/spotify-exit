"""Tests for the export request layer.

The bug these guard against: a single failed request mid-pagination used to be
swallowed, so a half-finished export was written out, reported as successful,
and marked complete - which made `--resume` skip it.
"""

import pytest
import requests

import spotify_export
from spotify_export import SpotifyExporter, SpotifyRequestError


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.text = str(self._json)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._json


class ResponseQueue(list):
    """Responses handed out in order, plus a record of the calls made."""

    def __init__(self):
        super().__init__()
        self.calls = []


@pytest.fixture
def slept(monkeypatch):
    """Record sleep durations instead of actually waiting."""
    recorded = []
    monkeypatch.setattr(spotify_export.time, "sleep", recorded.append)
    return recorded


@pytest.fixture
def exporter(tmp_path, monkeypatch, slept):
    """An exporter writing to a temp dir, which never really sleeps."""
    monkeypatch.chdir(tmp_path)
    return SpotifyExporter("test-token")


@pytest.fixture
def responses(exporter, monkeypatch):
    queue = ResponseQueue()

    def fake_get(url, **kwargs):
        queue.calls.append((url, kwargs.get("params")))
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(exporter.session, "get", fake_get)
    return queue


def page(items, total, next_url=None):
    return FakeResponse(json_data={"items": items, "total": total, "next": next_url})


# --- the truncation bug -------------------------------------------------


def test_failure_mid_pagination_raises_instead_of_truncating(exporter, responses):
    """This is the regression: page 1 succeeds, page 2 dies permanently."""
    responses.append(page([{"id": 1}], total=4, next_url="more"))
    responses.extend(
        FakeResponse(status_code=500) for _ in range(SpotifyExporter.MAX_RETRIES)
    )

    with pytest.raises(SpotifyRequestError):
        exporter._paginate("me/tracks", limit=1)


def test_short_read_is_rejected_even_when_every_request_succeeds(exporter, responses):
    """Spotify says 10 items exist but pagination ends after 1."""
    responses.append(page([{"id": 1}], total=10, next_url=None))

    with pytest.raises(SpotifyRequestError, match="expected 10 items but collected 1"):
        exporter._paginate("me/tracks")


def test_complete_pagination_returns_every_item(exporter, responses):
    responses.append(page([{"id": 1}, {"id": 2}], total=4, next_url="more"))
    responses.append(page([{"id": 3}, {"id": 4}], total=4, next_url=None))

    assert exporter._paginate("me/tracks", limit=2) == [
        {"id": 1},
        {"id": 2},
        {"id": 3},
        {"id": 4},
    ]


def test_response_without_items_raises(exporter, responses):
    responses.append(FakeResponse(json_data={"error": "nope"}))

    with pytest.raises(SpotifyRequestError, match="no 'items'"):
        exporter._paginate("me/tracks")


# --- a library that changes mid-export is not data loss -----------------


def test_library_shrinking_mid_export_warns_but_succeeds(exporter, responses, capsys):
    """A playlist deleted while the export runs shouldn't abort it."""
    responses.append(page([{"id": 1}, {"id": 2}], total=4, next_url="more"))
    responses.append(page([{"id": 3}], total=3, next_url=None))

    result = exporter._paginate("me/tracks", limit=2)

    assert len(result) == 3
    assert "library changed during export" in capsys.readouterr().out


def test_collecting_more_than_the_reported_total_is_not_an_error(exporter, responses):
    """An item added mid-export is never truncation."""
    responses.append(page([{"id": 1}, {"id": 2}, {"id": 3}], total=2, next_url=None))

    assert len(exporter._paginate("me/tracks")) == 3


def test_missing_total_is_tolerated(exporter, responses):
    """Not every endpoint reports a total; absence must not fail the export."""
    responses.append(FakeResponse(json_data={"items": [{"id": 1}], "next": None}))

    assert exporter._paginate("me/tracks") == [{"id": 1}]


# --- rate limiting ------------------------------------------------------


def test_rate_limit_is_retried_after_the_requested_delay(exporter, responses, slept):
    responses.append(FakeResponse(status_code=429, headers={"Retry-After": "7"}))
    responses.append(FakeResponse(json_data={"ok": True}))

    assert exporter._make_request("me") == {"ok": True}
    assert 7 in slept


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "soon"}])
def test_unusable_retry_after_falls_back_to_a_sane_wait(
    exporter, responses, slept, headers
):
    responses.append(FakeResponse(status_code=429, headers=headers))
    responses.append(FakeResponse(json_data={"ok": True}))

    exporter._make_request("me")

    assert any(delay >= 1 for delay in slept)


def test_endless_rate_limiting_eventually_gives_up(exporter, responses):
    responses.extend(
        FakeResponse(status_code=429)
        for _ in range(SpotifyExporter.MAX_RATE_LIMIT_WAITS + 1)
    )

    with pytest.raises(SpotifyRequestError, match="still rate limited"):
        exporter._make_request("me")


def test_being_rate_limited_slows_subsequent_requests(exporter, responses, slept):
    """A well-behaved export pays no flat tax; a throttled one backs off."""
    assert exporter.throttle == 0

    responses.append(FakeResponse(status_code=429, headers={"Retry-After": "1"}))
    responses.append(FakeResponse(json_data={"ok": True}))
    exporter._make_request("me")

    assert exporter.throttle > 0


# --- transient failures -------------------------------------------------


def test_server_error_is_retried_then_succeeds(exporter, responses):
    responses.append(FakeResponse(status_code=503))
    responses.append(FakeResponse(status_code=503))
    responses.append(FakeResponse(json_data={"ok": True}))

    assert exporter._make_request("me") == {"ok": True}


def test_network_error_is_retried_then_succeeds(exporter, responses):
    responses.append(requests.exceptions.ConnectionError("reset"))
    responses.append(FakeResponse(json_data={"ok": True}))

    assert exporter._make_request("me") == {"ok": True}


def test_persistent_network_error_raises(exporter, responses):
    responses.extend(
        requests.exceptions.ConnectionError("reset")
        for _ in range(SpotifyExporter.MAX_RETRIES)
    )

    with pytest.raises(SpotifyRequestError, match="network error"):
        exporter._make_request("me")


def test_backoff_is_capped(exporter, responses, slept):
    """Otherwise a long retry chain could sleep for minutes."""
    responses.extend(
        FakeResponse(status_code=503) for _ in range(SpotifyExporter.MAX_RETRIES)
    )

    with pytest.raises(SpotifyRequestError):
        exporter._make_request("me")

    assert slept, "expected the retries to back off"
    assert max(slept) <= SpotifyExporter.MAX_BACKOFF * 1.25


def test_client_error_raises_immediately_without_retrying(exporter, responses):
    """A 404 won't fix itself, so it shouldn't burn the retry budget."""
    responses.append(FakeResponse(status_code=404, json_data={"error": "not found"}))

    with pytest.raises(SpotifyRequestError, match="404"):
        exporter._make_request("me/nope")

    assert len(responses.calls) == 1


# --- token refresh ------------------------------------------------------


def test_401_refreshes_the_token_and_retries(exporter, responses, monkeypatch):
    responses.append(FakeResponse(status_code=401))
    responses.append(FakeResponse(json_data={"ok": True}))
    monkeypatch.setattr(exporter, "refresh_access_token", lambda: True)

    assert exporter._make_request("me") == {"ok": True}


def test_401_after_a_successful_refresh_gives_up(exporter, responses, monkeypatch):
    """Otherwise a token that can't be fixed loops forever."""
    responses.extend(FakeResponse(status_code=401) for _ in range(3))
    monkeypatch.setattr(exporter, "refresh_access_token", lambda: True)

    with pytest.raises(SpotifyRequestError, match="still unauthorized"):
        exporter._make_request("me")


def test_401_with_a_failed_refresh_raises(exporter, responses, monkeypatch):
    responses.append(FakeResponse(status_code=401))
    monkeypatch.setattr(exporter, "refresh_access_token", lambda: False)

    with pytest.raises(SpotifyRequestError, match="authentication failed"):
        exporter._make_request("me")


# --- the other collection paths got the same invariant ------------------


def test_followed_artists_short_read_is_rejected(exporter, responses):
    """Cursor pagination used to skip the completeness check entirely."""
    responses.append(
        FakeResponse(
            json_data={"artists": {"items": [{"id": "a"}], "total": 5, "next": None}}
        )
    )

    with pytest.raises(SpotifyRequestError, match="expected 5 items"):
        exporter.export_followed_artists()


def test_followed_artists_malformed_response_raises(exporter, responses):
    responses.append(FakeResponse(json_data={"unexpected": True}))

    with pytest.raises(SpotifyRequestError, match="no 'artists'"):
        exporter.export_followed_artists()


@pytest.mark.parametrize("method", ["export_top_tracks", "export_top_artists"])
def test_top_items_reject_a_malformed_response(exporter, responses, method):
    """These used to turn a missing key into an empty list."""
    responses.append(FakeResponse(json_data={"error": "nope"}))

    with pytest.raises(SpotifyRequestError, match="no 'items'"):
        getattr(exporter, method)()


def test_uses_one_session_for_every_request(exporter):
    """Hundreds of paginated calls shouldn't each open a new connection."""
    assert isinstance(exporter.session, requests.Session)
    assert exporter.session.headers["Authorization"] == "Bearer test-token"


def test_refreshed_token_is_applied_to_the_session(exporter, monkeypatch):
    """A refresh that didn't update the session would 401 forever."""
    monkeypatch.setattr(
        spotify_export,
        "request_token",
        lambda *a, **k: {"access_token": "new-token"},
    )
    monkeypatch.setattr(spotify_export, "write_env", lambda **kwargs: None)
    exporter.client_id = "id"
    exporter.client_secret = "secret"
    exporter.refresh_token = "refresh"

    assert exporter.refresh_access_token() is True
    assert exporter.session.headers["Authorization"] == "Bearer new-token"
