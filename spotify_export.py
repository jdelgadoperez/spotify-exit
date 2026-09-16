#!/usr/bin/env python3
"""
Spotify Data Export Script
Exports all your Spotify data including playlists, saved tracks, albums, artists, and podcasts.
"""

import requests
import json
import csv
import os
import random
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

# Importing this loads .env and shares the token endpoint with get_token.py
from spotify_config import request_token, write_env


class SpotifyRequestError(Exception):
    """A Spotify API request failed and the export cannot be trusted."""


class SpotifyExporter:
    """Export Spotify user data using the Spotify Web API."""

    BASE_URL = "https://api.spotify.com/v1"

    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 5  # for network errors and 5xx
    MAX_RATE_LIMIT_WAITS = 10  # 429s are expected, so budget them separately
    BACKOFF_BASE = 2
    MAX_BACKOFF = 30
    # Applied between requests only after Spotify has rate limited us once, so
    # a well-behaved export pays no flat tax but a throttled one backs off.
    THROTTLE_STEP = 0.1
    MAX_THROTTLE = 1.0

    def __init__(
        self,
        access_token: str,
        client_id: str = None,
        client_secret: str = None,
        refresh_token: str = None,
        resume: bool = False,
    ):
        """Initialize with Spotify access token."""
        self.access_token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
        )
        self.throttle = 0.0
        self.user_id = None
        self.exports_dir = "exports/spotify"
        self.resume = resume
        self.progress_file = os.path.join(self.exports_dir, ".export_progress.json")
        os.makedirs(self.exports_dir, exist_ok=True)

        # Set or load timestamp for this export session
        if resume:
            progress = self._load_progress()
            self.timestamp = progress.get(
                "timestamp", datetime.now().strftime("%Y%m%d_%H%M%S")
            )
        else:
            self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Save timestamp to progress file
            self._save_progress({"timestamp": self.timestamp})

    def refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            print("\nERROR: Cannot refresh token - missing credentials")
            print("Please run: uv run get_token.py")
            return False

        token_data = request_token(
            self.client_id,
            self.client_secret,
            {"grant_type": "refresh_token", "refresh_token": self.refresh_token},
        )

        if not token_data:
            return False

        self.access_token = token_data["access_token"]
        self.session.headers["Authorization"] = f"Bearer {self.access_token}"
        write_env(SPOTIFY_ACCESS_TOKEN=self.access_token)

        print("✓ Access token refreshed successfully")
        return True

    def _safe_join_artists(self, artists: List[Dict]) -> str:
        """Safely join artist names, handling None values."""
        if not artists:
            return "Unknown Artist"
        artist_names = [artist.get("name") or "Unknown" for artist in artists if artist]
        return ", ".join(artist_names) if artist_names else "Unknown Artist"

    def _load_progress(self) -> Dict:
        """Load export progress from file."""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_progress(self, progress: Dict):
        """Save export progress to file."""
        with open(self.progress_file, "w") as f:
            json.dump(progress, f, indent=2)

    def _mark_complete(self, section: str, timestamp: str):
        """Mark a section as complete."""
        progress = self._load_progress()
        if timestamp not in progress:
            progress[timestamp] = {}
        progress[timestamp][section] = True
        self._save_progress(progress)

    def _mark_playlist_complete(self, playlist_id: str, timestamp: str):
        """Mark a playlist as exported."""
        progress = self._load_progress()
        if timestamp not in progress:
            progress[timestamp] = {}
        if "playlists" not in progress[timestamp]:
            progress[timestamp]["playlists"] = []
        if playlist_id not in progress[timestamp]["playlists"]:
            progress[timestamp]["playlists"].append(playlist_id)
        self._save_progress(progress)

    def _is_complete(self, section: str, timestamp: str) -> bool:
        """Check if a section is already complete."""
        progress = self._load_progress()
        return progress.get(timestamp, {}).get(section, False)

    def _is_playlist_complete(self, playlist_id: str, timestamp: str) -> bool:
        """Check if a playlist was already exported."""
        progress = self._load_progress()
        playlists = progress.get(timestamp, {}).get("playlists", [])
        return playlist_id in playlists

    @staticmethod
    def _retry_after_seconds(response) -> int:
        """How long Spotify asked us to wait, with a sane fallback."""
        try:
            return max(1, int(response.headers.get("Retry-After", 5)))
        except (TypeError, ValueError):
            return 5

    def _retry_or_give_up(self, failures: int, endpoint: str, reason: str):
        """Sleep before retrying, or raise once the retry budget is spent."""
        if failures >= self.MAX_RETRIES:
            raise SpotifyRequestError(
                f"{endpoint}: {reason} (gave up after {failures} attempts)"
            )

        # Jitter so concurrent retries don't re-collide on the same schedule.
        delay = min(self.BACKOFF_BASE**failures, self.MAX_BACKOFF)
        delay += random.uniform(0, delay / 4)
        print(f"  ⚠ {endpoint}: {reason}")
        print(f"    retrying in {delay:.1f}s ({failures}/{self.MAX_RETRIES})")
        time.sleep(delay)

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """GET an endpoint, retrying transient failures.

        Raises SpotifyRequestError rather than returning a partial or empty
        result - a caller that silently treats a failure as "no more data"
        produces a truncated export that looks complete.
        """
        url = f"{self.BASE_URL}/{endpoint}"
        failures = 0
        rate_limit_waits = 0
        refreshed = False

        while True:
            try:
                response = self.session.get(
                    url, params=params, timeout=self.REQUEST_TIMEOUT
                )
            except requests.exceptions.RequestException as e:
                failures += 1
                self._retry_or_give_up(failures, endpoint, f"network error: {e}")
                continue

            if response.status_code == 401:
                if refreshed:
                    raise SpotifyRequestError(
                        f"{endpoint}: still unauthorized after refreshing the token"
                    )
                print("\n⚠ Token expired, attempting to refresh...")
                if not self.refresh_access_token():
                    raise SpotifyRequestError(
                        "authentication failed - run: uv run get_token.py"
                    )
                refreshed = True
                continue

            if response.status_code == 429:
                rate_limit_waits += 1
                if rate_limit_waits > self.MAX_RATE_LIMIT_WAITS:
                    raise SpotifyRequestError(
                        f"{endpoint}: still rate limited after "
                        f"{self.MAX_RATE_LIMIT_WAITS} waits"
                    )
                # Back off between subsequent requests too, not just this one.
                self.throttle = min(
                    self.throttle + self.THROTTLE_STEP, self.MAX_THROTTLE
                )
                delay = self._retry_after_seconds(response)
                print(f"  ⏳ Rate limited by Spotify, waiting {delay}s...")
                time.sleep(delay)
                continue

            if response.status_code >= 500:
                failures += 1
                self._retry_or_give_up(
                    failures, endpoint, f"server error {response.status_code}"
                )
                continue

            if not response.ok:
                raise SpotifyRequestError(
                    f"{endpoint} returned {response.status_code}: {response.text}"
                )

            if self.throttle:
                time.sleep(self.throttle)
            return response.json()

    @staticmethod
    def _page_items(endpoint: str, page: Dict, key: str = "items") -> List[Dict]:
        """Pull the item list out of a page, refusing a malformed response.

        A missing key must not quietly become an empty list - that is how a
        failed fetch turns into an export that looks complete.
        """
        if key not in page:
            raise SpotifyRequestError(
                f"{endpoint}: response had no '{key}' (got keys: {sorted(page)})"
            )
        return page[key]

    @staticmethod
    def _verify_complete(
        endpoint: str, collected: int, first_total, last_total
    ) -> None:
        """Check a finished collection against the totals Spotify reported.

        Spotify re-reports the total on every page, so a total that changed
        mid-export means the library itself changed - a playlist deleted, a
        track saved from another device. That is not data loss, so it warns.
        A short read against a total that never moved is a lost page, and the
        export cannot be trusted.
        """
        if first_total is None or last_total is None:
            return

        if first_total != last_total:
            print(
                f"  ⚠ {endpoint}: library changed during export "
                f"({first_total} → {last_total} items); collected {collected}"
            )
            return

        if collected < first_total:
            raise SpotifyRequestError(
                f"{endpoint}: expected {first_total} items but collected "
                f"{collected}. The export would be incomplete; re-run with "
                "--resume."
            )

    def _paginate(self, endpoint: str, limit: int = 50) -> List[Dict]:
        """Collect every page of a paginated endpoint.

        Spotify reports how many items exist, so the result is checked against
        that count: a short read means the export is incomplete and must not
        be recorded as finished.
        """
        items = []
        offset = 0
        first_total = None
        last_total = None

        while True:
            page = self._make_request(endpoint, {"limit": limit, "offset": offset})
            items.extend(self._page_items(endpoint, page))

            last_total = page.get("total")
            if first_total is None:
                first_total = last_total

            progress = f"{len(items)} of {last_total}" if last_total else len(items)
            print(f"  Fetched {progress} items...")

            if not page.get("next"):
                break

            offset += limit

        self._verify_complete(endpoint, len(items), first_total, last_total)
        return items

    def get_user_profile(self) -> Dict:
        """Get current user's profile."""
        print("Fetching user profile...")
        profile = self._make_request("me")
        self.user_id = profile.get("id")
        return profile

    def export_saved_tracks(self) -> List[Dict]:
        """Export all saved tracks."""
        print("\nExporting saved tracks...")
        saved_tracks = self._paginate("me/tracks")

        tracks_data = []
        for item in saved_tracks:
            track = item.get("track", {})
            tracks_data.append(
                {
                    "name": track.get("name") or "Unknown Track",
                    "artist": self._safe_join_artists(track.get("artists", [])),
                    "album": track.get("album", {}).get("name") or "Unknown Album",
                    "duration_ms": track.get("duration_ms"),
                    "release_date": track.get("album", {}).get("release_date"),
                    "added_at": item.get("added_at"),
                    "spotify_url": track.get("external_urls", {}).get("spotify"),
                    "uri": track.get("uri"),
                    "isrc": track.get("external_ids", {}).get("isrc"),
                }
            )

        print(f"Exported {len(tracks_data)} saved tracks")
        return tracks_data

    def export_playlists(self) -> List[Dict]:
        """Export all playlists with their tracks, saving each immediately."""
        print("\nExporting playlists...")
        playlists = self._paginate("me/playlists")

        playlists_data = []
        skipped = 0
        exported = 0

        for playlist in playlists:
            playlist_id = playlist.get("id")
            playlist_name = playlist.get("name") or "Unnamed Playlist"

            # Check if playlist already exported (resume mode)
            if self.resume and self._is_playlist_complete(playlist_id, self.timestamp):
                print(f"  ⏭ Skipping playlist (already exported): {playlist_name}")
                skipped += 1
                # Still add to playlists_data for final JSON (load from file if needed)
                continue

            print(f"  Fetching tracks for playlist: {playlist_name}")

            # Get all tracks in this playlist
            tracks = self._paginate(f"playlists/{playlist_id}/tracks")

            track_list = []
            for item in tracks:
                track = item.get("track")
                if track:  # Sometimes track can be None for deleted songs
                    track_list.append(
                        {
                            "name": track.get("name") or "Unknown Track",
                            "artist": self._safe_join_artists(track.get("artists", [])),
                            "album": track.get("album", {}).get("name")
                            or "Unknown Album",
                            "added_at": item.get("added_at"),
                            "spotify_url": track.get("external_urls", {}).get(
                                "spotify"
                            ),
                            "uri": track.get("uri"),
                        }
                    )

            playlist_data = {
                "name": playlist_name,
                "description": playlist.get("description"),
                "owner": playlist.get("owner", {}).get("display_name"),
                "public": playlist.get("public"),
                "collaborative": playlist.get("collaborative"),
                "tracks_total": playlist.get("tracks", {}).get("total"),
                "spotify_url": playlist.get("external_urls", {}).get("spotify"),
                "uri": playlist.get("uri"),
                "tracks": track_list,
            }
            playlists_data.append(playlist_data)

            # Save this playlist immediately to CSV
            if track_list:
                safe_name = playlist_name.replace("/", "-").replace("\\", "-")
                safe_name = "".join(
                    c for c in safe_name if c.isalnum() or c in (" ", "-", "_")
                ).strip()
                safe_name = safe_name[:100]  # Limit filename length
                self.save_to_csv(
                    track_list, f"playlist_{safe_name}_{self.timestamp}.csv"
                )

                # Mark as complete
                self._mark_playlist_complete(playlist_id, self.timestamp)
                exported += 1

        if skipped > 0:
            print(
                f"Exported {exported} playlists, skipped {skipped} already-exported playlists"
            )
        else:
            print(f"Exported {len(playlists_data)} playlists")
        return playlists_data

    def export_saved_albums(self) -> List[Dict]:
        """Export all saved albums."""
        print("\nExporting saved albums...")
        saved_albums = self._paginate("me/albums")

        albums_data = []
        for item in saved_albums:
            album = item.get("album", {})
            albums_data.append(
                {
                    "name": album.get("name") or "Unknown Album",
                    "artist": self._safe_join_artists(album.get("artists", [])),
                    "release_date": album.get("release_date"),
                    "total_tracks": album.get("total_tracks"),
                    "added_at": item.get("added_at"),
                    "spotify_url": album.get("external_urls", {}).get("spotify"),
                    "uri": album.get("uri"),
                    "upc": album.get("external_ids", {}).get("upc"),
                }
            )

        print(f"Exported {len(albums_data)} saved albums")
        return albums_data

    def export_followed_artists(self) -> List[Dict]:
        """Export all followed artists."""
        print("\nExporting followed artists...")

        artists_data = []
        after = None
        first_total = None
        last_total = None

        while True:
            params = {"type": "artist", "limit": 50}
            if after:
                params["after"] = after

            response = self._make_request("me/following", params)
            artists = self._page_items("me/following", response, key="artists")
            batch = self._page_items("me/following", artists)

            last_total = artists.get("total")
            if first_total is None:
                first_total = last_total

            for artist in batch:
                artists_data.append(
                    {
                        "name": artist.get("name") or "Unknown Artist",
                        "genres": ", ".join(artist.get("genres", [])),
                        "popularity": artist.get("popularity"),
                        "followers": artist.get("followers", {}).get("total"),
                        "spotify_url": artist.get("external_urls", {}).get("spotify"),
                        "uri": artist.get("uri"),
                    }
                )

            print(f"  Fetched {len(artists_data)} artists...")

            if not batch or artists.get("next") is None:
                break

            # Get cursor for next page
            after = batch[-1].get("id")

        self._verify_complete(
            "me/following", len(artists_data), first_total, last_total
        )

        print(f"Exported {len(artists_data)} followed artists")
        return artists_data

    def export_saved_shows(self) -> List[Dict]:
        """Export all saved podcasts/shows."""
        print("\nExporting saved podcasts/shows...")
        saved_shows = self._paginate("me/shows")

        shows_data = []
        for item in saved_shows:
            show = item.get("show", {})
            shows_data.append(
                {
                    "name": show.get("name") or "Unknown Show",
                    "publisher": show.get("publisher") or "Unknown Publisher",
                    "description": show.get("description") or "",
                    "total_episodes": show.get("total_episodes"),
                    "added_at": item.get("added_at"),
                    "spotify_url": show.get("external_urls", {}).get("spotify"),
                    "uri": show.get("uri"),
                }
            )

        print(f"Exported {len(shows_data)} saved shows")
        return shows_data

    def export_top_tracks(self, time_range: str = "long_term") -> List[Dict]:
        """Export top tracks (long_term = all time, medium_term = 6 months, short_term = 4 weeks)."""
        print(f"\nExporting top tracks ({time_range})...")

        params = {"limit": 50, "time_range": time_range}
        response = self._make_request("me/top/tracks", params)

        tracks_data = []
        for track in self._page_items("me/top/tracks", response):
            tracks_data.append(
                {
                    "name": track.get("name") or "Unknown Track",
                    "artist": self._safe_join_artists(track.get("artists", [])),
                    "album": track.get("album", {}).get("name") or "Unknown Album",
                    "popularity": track.get("popularity"),
                    "spotify_url": track.get("external_urls", {}).get("spotify"),
                    "uri": track.get("uri"),
                }
            )

        print(f"Exported {len(tracks_data)} top tracks")
        return tracks_data

    def export_top_artists(self, time_range: str = "long_term") -> List[Dict]:
        """Export top artists (long_term = all time, medium_term = 6 months, short_term = 4 weeks)."""
        print(f"\nExporting top artists ({time_range})...")

        params = {"limit": 50, "time_range": time_range}
        response = self._make_request("me/top/artists", params)

        artists_data = []
        for artist in self._page_items("me/top/artists", response):
            artists_data.append(
                {
                    "name": artist.get("name") or "Unknown Artist",
                    "genres": ", ".join(artist.get("genres", [])),
                    "popularity": artist.get("popularity"),
                    "followers": artist.get("followers", {}).get("total"),
                    "spotify_url": artist.get("external_urls", {}).get("spotify"),
                    "uri": artist.get("uri"),
                }
            )

        print(f"Exported {len(artists_data)} top artists")
        return artists_data

    def save_to_json(self, data: Dict, filename: str):
        """Save data to JSON file."""
        filepath = os.path.join(self.exports_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved to {filepath}")

    def save_to_csv(self, data: List[Dict], filename: str):
        """Save data to CSV file."""
        if not data:
            print(f"No data to save for {filename}")
            return

        filepath = os.path.join(self.exports_dir, filename)
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        print(f"Saved to {filepath}")

    def export_all(self):
        """Export all Spotify data with incremental saving and resume capability."""
        print("=" * 60)
        if self.resume:
            print("SPOTIFY DATA EXPORT (Resume Mode)")
            print("=" * 60)
            print(f"Resuming export session: {self.timestamp}")
            print("Skipping already-exported items\n")
        else:
            print("SPOTIFY DATA EXPORT (Incremental Save Mode)")
            print("=" * 60)
            print(f"Export session: {self.timestamp}")
            print("Data will be saved after each section is fetched\n")

        # Get user profile - also the first request, so it validates the token
        profile = self.get_user_profile()
        print(f"✓ Token valid for user: {profile.get('display_name') or profile.get('id')}")
        profile_data = {
            "id": profile.get("id"),
            "display_name": profile.get("display_name"),
            "email": profile.get("email"),
            "country": profile.get("country"),
            "product": profile.get("product"),
            "followers": profile.get("followers", {}).get("total"),
        }

        # Export and save tracks immediately
        if not self.resume or not self._is_complete("saved_tracks", self.timestamp):
            saved_tracks = self.export_saved_tracks()
            if saved_tracks:
                self.save_to_csv(saved_tracks, f"saved_tracks_{self.timestamp}.csv")
                self._mark_complete("saved_tracks", self.timestamp)
                print(f"✓ Saved tracks to CSV\n")
        else:
            print("⏭ Skipping saved tracks (already exported)\n")
            saved_tracks = []

        # Export and save playlists immediately (including individual playlist files)
        playlists = self.export_playlists()
        self._mark_complete("playlists", self.timestamp)
        print(f"✓ Saved playlist CSV files\n")

        # Export and save albums immediately
        if not self.resume or not self._is_complete("saved_albums", self.timestamp):
            saved_albums = self.export_saved_albums()
            if saved_albums:
                self.save_to_csv(saved_albums, f"saved_albums_{self.timestamp}.csv")
                self._mark_complete("saved_albums", self.timestamp)
                print(f"✓ Saved albums to CSV\n")
        else:
            print("⏭ Skipping saved albums (already exported)\n")
            saved_albums = []

        # Export and save followed artists immediately
        if not self.resume or not self._is_complete("followed_artists", self.timestamp):
            followed_artists = self.export_followed_artists()
            if followed_artists:
                self.save_to_csv(
                    followed_artists, f"followed_artists_{self.timestamp}.csv"
                )
                self._mark_complete("followed_artists", self.timestamp)
                print(f"✓ Saved followed artists to CSV\n")
        else:
            print("⏭ Skipping followed artists (already exported)\n")
            followed_artists = []

        # Export and save shows immediately
        if not self.resume or not self._is_complete("saved_shows", self.timestamp):
            saved_shows = self.export_saved_shows()
            if saved_shows:
                self.save_to_csv(saved_shows, f"saved_shows_{self.timestamp}.csv")
                self._mark_complete("saved_shows", self.timestamp)
                print(f"✓ Saved shows to CSV\n")
        else:
            print("⏭ Skipping saved shows (already exported)\n")
            saved_shows = []

        # Export and save top tracks immediately
        if not self.resume or not self._is_complete("top_tracks", self.timestamp):
            top_tracks_long = self.export_top_tracks("long_term")
            if top_tracks_long:
                self.save_to_csv(
                    top_tracks_long, f"top_tracks_all_time_{self.timestamp}.csv"
                )
                self._mark_complete("top_tracks", self.timestamp)
                print(f"✓ Saved top tracks to CSV\n")
        else:
            print("⏭ Skipping top tracks (already exported)\n")
            top_tracks_long = []

        # Export and save top artists immediately
        if not self.resume or not self._is_complete("top_artists", self.timestamp):
            top_artists_long = self.export_top_artists("long_term")
            if top_artists_long:
                self.save_to_csv(
                    top_artists_long, f"top_artists_all_time_{self.timestamp}.csv"
                )
                self._mark_complete("top_artists", self.timestamp)
                print(f"✓ Saved top artists to CSV\n")
        else:
            print("⏭ Skipping top artists (already exported)\n")
            top_artists_long = []

        # Create and save comprehensive JSON export at the end
        if not self.resume or not self._is_complete("full_json", self.timestamp):
            full_export = {
                "export_date": datetime.now().isoformat(),
                "user_profile": profile_data,
                "saved_tracks": saved_tracks,
                "playlists": playlists,
                "saved_albums": saved_albums,
                "followed_artists": followed_artists,
                "saved_shows": saved_shows,
                "top_tracks_all_time": top_tracks_long,
                "top_artists_all_time": top_artists_long,
            }
            self.save_to_json(full_export, f"spotify_full_export_{self.timestamp}.json")
            self._mark_complete("full_json", self.timestamp)
            print(f"✓ Saved complete export to JSON\n")

        print("=" * 60)
        print("EXPORT COMPLETE!")
        print("=" * 60)
        print(f"\nSummary:")
        print(f"  - Saved Tracks: {len(saved_tracks) if saved_tracks else 'skipped'}")
        print(f"  - Playlists: {len(playlists)}")
        print(f"  - Saved Albums: {len(saved_albums) if saved_albums else 'skipped'}")
        print(
            f"  - Followed Artists: {len(followed_artists) if followed_artists else 'skipped'}"
        )
        print(f"  - Saved Shows: {len(saved_shows) if saved_shows else 'skipped'}")
        print(f"\nAll files saved to '{self.exports_dir}/' directory")

        # Clean up progress file if export completed successfully
        if os.path.exists(self.progress_file):
            try:
                os.remove(self.progress_file)
                print(f"✓ Cleaned up progress tracking file")
            except:
                pass


def run_export(exporter: "SpotifyExporter"):
    """Run the export, reporting an incomplete run as a failure.

    Anything already written stays on disk, so `--resume` picks up from there
    rather than starting over.
    """
    try:
        exporter.export_all()
    except SpotifyRequestError as e:
        print("\n" + "=" * 60)
        print("EXPORT INCOMPLETE")
        print("=" * 60)
        print(f"\n{e}\n")
        print("Any data already exported has been saved. To continue:")
        print("  uv run spotify_export.py --resume")
        sys.exit(1)


def main():
    """Main execution function."""

    # Check for resume flag
    resume = "--resume" in sys.argv

    access_token = os.getenv("SPOTIFY_ACCESS_TOKEN")
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")

    if not access_token:
        print("ERROR: SPOTIFY_ACCESS_TOKEN not found")
        print("\nTo authenticate:")
        print("  1. cp .env.example .env")
        print("  2. Fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET")
        print("  3. uv run get_token.py")
        print("\nSee README.md for the full walkthrough")
        return

    exporter = SpotifyExporter(
        access_token, client_id, client_secret, refresh_token, resume=resume
    )
    run_export(exporter)


if __name__ == "__main__":
    main()
