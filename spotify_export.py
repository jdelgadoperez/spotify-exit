#!/usr/bin/env python3
"""
Spotify Data Export Script
Exports all your Spotify data including playlists, saved tracks, albums, artists, and podcasts.
"""

import requests
import json
import csv
import os
import time
import base64
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SpotifyExporter:
    """Export Spotify user data using the Spotify Web API."""

    BASE_URL = "https://api.spotify.com/v1"

    def __init__(self, access_token: str, client_id: str = None, client_secret: str = None, refresh_token: str = None, resume: bool = False):
        """Initialize with Spotify access token."""
        self.access_token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        self.user_id = None
        self.exports_dir = "exports"
        self.resume = resume
        self.progress_file = os.path.join(self.exports_dir, ".export_progress.json")
        os.makedirs(self.exports_dir, exist_ok=True)

        # Set or load timestamp for this export session
        if resume:
            progress = self._load_progress()
            self.timestamp = progress.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
        else:
            self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Save timestamp to progress file
            self._save_progress({"timestamp": self.timestamp})

    def refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            print("\nERROR: Cannot refresh token - missing credentials")
            print("Please run: python get_token.py")
            return False

        credentials = f"{self.client_id}:{self.client_secret}"
        b64_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {b64_credentials}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }

        try:
            response = requests.post(
                "https://accounts.spotify.com/api/token",
                headers=headers,
                data=data
            )
            response.raise_for_status()

            token_data = response.json()
            self.access_token = token_data.get("access_token")
            self.headers["Authorization"] = f"Bearer {self.access_token}"

            # Update .env file with new token
            self._update_env_token(self.access_token)

            print("✓ Access token refreshed successfully")
            return True

        except requests.exceptions.RequestException as e:
            print(f"ERROR refreshing token: {e}")
            return False

    def _update_env_token(self, new_token: str):
        """Update the access token in .env file."""
        env_path = ".env"
        if not os.path.exists(env_path):
            return

        with open(env_path, 'r') as f:
            lines = f.readlines()

        with open(env_path, 'w') as f:
            for line in lines:
                if line.startswith('SPOTIFY_ACCESS_TOKEN='):
                    f.write(f'SPOTIFY_ACCESS_TOKEN={new_token}\n')
                else:
                    f.write(line)

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
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_progress(self, progress: Dict):
        """Save export progress to file."""
        with open(self.progress_file, 'w') as f:
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

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make authenticated request to Spotify API with rate limiting."""
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params)

            # Handle 401 - try to refresh token
            if response.status_code == 401:
                print(f"\n⚠ Token expired, attempting to refresh...")
                if self.refresh_access_token():
                    # Retry request with new token
                    response = requests.get(url, headers=self.headers, params=params)
                else:
                    print("\nERROR: Token refresh failed")
                    print("Please run: python get_token.py")
                    raise Exception("Authentication failed - please refresh token")

            response.raise_for_status()
            time.sleep(0.1)  # Rate limiting
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {endpoint}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status: {e.response.status_code}")
                print(f"Response body: {e.response.text}")
            return {}

    def _paginate(self, endpoint: str, limit: int = 50) -> List[Dict]:
        """Paginate through API results."""
        items = []
        offset = 0

        while True:
            params = {"limit": limit, "offset": offset}
            response = self._make_request(endpoint, params)

            if not response or "items" not in response:
                break

            batch = response["items"]
            if not batch:
                break

            items.extend(batch)
            print(f"  Fetched {len(items)} items...")

            if response.get("next") is None:
                break

            offset += limit

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
            tracks_data.append({
                "name": track.get("name") or "Unknown Track",
                "artist": self._safe_join_artists(track.get("artists", [])),
                "album": track.get("album", {}).get("name") or "Unknown Album",
                "duration_ms": track.get("duration_ms"),
                "release_date": track.get("album", {}).get("release_date"),
                "added_at": item.get("added_at"),
                "spotify_url": track.get("external_urls", {}).get("spotify"),
                "uri": track.get("uri"),
                "isrc": track.get("external_ids", {}).get("isrc")
            })

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
                    track_list.append({
                        "name": track.get("name") or "Unknown Track",
                        "artist": self._safe_join_artists(track.get("artists", [])),
                        "album": track.get("album", {}).get("name") or "Unknown Album",
                        "added_at": item.get("added_at"),
                        "spotify_url": track.get("external_urls", {}).get("spotify"),
                        "uri": track.get("uri")
                    })

            playlist_data = {
                "name": playlist_name,
                "description": playlist.get("description"),
                "owner": playlist.get("owner", {}).get("display_name"),
                "public": playlist.get("public"),
                "collaborative": playlist.get("collaborative"),
                "tracks_total": playlist.get("tracks", {}).get("total"),
                "spotify_url": playlist.get("external_urls", {}).get("spotify"),
                "uri": playlist.get("uri"),
                "tracks": track_list
            }
            playlists_data.append(playlist_data)

            # Save this playlist immediately to CSV
            if track_list:
                safe_name = playlist_name.replace("/", "-").replace("\\", "-")
                safe_name = "".join(c for c in safe_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_name = safe_name[:100]  # Limit filename length
                self.save_to_csv(track_list, f"playlist_{safe_name}_{self.timestamp}.csv")

                # Mark as complete
                self._mark_playlist_complete(playlist_id, self.timestamp)
                exported += 1

        if skipped > 0:
            print(f"Exported {exported} playlists, skipped {skipped} already-exported playlists")
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
            albums_data.append({
                "name": album.get("name") or "Unknown Album",
                "artist": self._safe_join_artists(album.get("artists", [])),
                "release_date": album.get("release_date"),
                "total_tracks": album.get("total_tracks"),
                "added_at": item.get("added_at"),
                "spotify_url": album.get("external_urls", {}).get("spotify"),
                "uri": album.get("uri"),
                "upc": album.get("external_ids", {}).get("upc")
            })

        print(f"Exported {len(albums_data)} saved albums")
        return albums_data

    def export_followed_artists(self) -> List[Dict]:
        """Export all followed artists."""
        print("\nExporting followed artists...")

        artists_data = []
        after = None

        while True:
            params = {"type": "artist", "limit": 50}
            if after:
                params["after"] = after

            response = self._make_request("me/following", params)

            if not response or "artists" not in response:
                break

            artists = response["artists"]
            batch = artists.get("items", [])

            if not batch:
                break

            for artist in batch:
                artists_data.append({
                    "name": artist.get("name") or "Unknown Artist",
                    "genres": ", ".join(artist.get("genres", [])),
                    "popularity": artist.get("popularity"),
                    "followers": artist.get("followers", {}).get("total"),
                    "spotify_url": artist.get("external_urls", {}).get("spotify"),
                    "uri": artist.get("uri")
                })

            print(f"  Fetched {len(artists_data)} artists...")

            if artists.get("next") is None:
                break

            # Get cursor for next page
            if batch:
                after = batch[-1].get("id")

        print(f"Exported {len(artists_data)} followed artists")
        return artists_data

    def export_saved_shows(self) -> List[Dict]:
        """Export all saved podcasts/shows."""
        print("\nExporting saved podcasts/shows...")
        saved_shows = self._paginate("me/shows")

        shows_data = []
        for item in saved_shows:
            show = item.get("show", {})
            shows_data.append({
                "name": show.get("name") or "Unknown Show",
                "publisher": show.get("publisher") or "Unknown Publisher",
                "description": show.get("description") or "",
                "total_episodes": show.get("total_episodes"),
                "added_at": item.get("added_at"),
                "spotify_url": show.get("external_urls", {}).get("spotify"),
                "uri": show.get("uri")
            })

        print(f"Exported {len(shows_data)} saved shows")
        return shows_data

    def export_top_tracks(self, time_range: str = "long_term") -> List[Dict]:
        """Export top tracks (long_term = all time, medium_term = 6 months, short_term = 4 weeks)."""
        print(f"\nExporting top tracks ({time_range})...")

        params = {"limit": 50, "time_range": time_range}
        response = self._make_request("me/top/tracks", params)

        tracks_data = []
        for track in response.get("items", []):
            tracks_data.append({
                "name": track.get("name") or "Unknown Track",
                "artist": self._safe_join_artists(track.get("artists", [])),
                "album": track.get("album", {}).get("name") or "Unknown Album",
                "popularity": track.get("popularity"),
                "spotify_url": track.get("external_urls", {}).get("spotify"),
                "uri": track.get("uri")
            })

        print(f"Exported {len(tracks_data)} top tracks")
        return tracks_data

    def export_top_artists(self, time_range: str = "long_term") -> List[Dict]:
        """Export top artists (long_term = all time, medium_term = 6 months, short_term = 4 weeks)."""
        print(f"\nExporting top artists ({time_range})...")

        params = {"limit": 50, "time_range": time_range}
        response = self._make_request("me/top/artists", params)

        artists_data = []
        for artist in response.get("items", []):
            artists_data.append({
                "name": artist.get("name") or "Unknown Artist",
                "genres": ", ".join(artist.get("genres", [])),
                "popularity": artist.get("popularity"),
                "followers": artist.get("followers", {}).get("total"),
                "spotify_url": artist.get("external_urls", {}).get("spotify"),
                "uri": artist.get("uri")
            })

        print(f"Exported {len(artists_data)} top artists")
        return artists_data

    def save_to_json(self, data: Dict, filename: str):
        """Save data to JSON file."""
        filepath = os.path.join(self.exports_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved to {filepath}")

    def save_to_csv(self, data: List[Dict], filename: str):
        """Save data to CSV file."""
        if not data:
            print(f"No data to save for {filename}")
            return

        filepath = os.path.join(self.exports_dir, filename)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
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

        # Get user profile
        profile = self.get_user_profile()
        profile_data = {
            "id": profile.get("id"),
            "display_name": profile.get("display_name"),
            "email": profile.get("email"),
            "country": profile.get("country"),
            "product": profile.get("product"),
            "followers": profile.get("followers", {}).get("total")
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
                self.save_to_csv(followed_artists, f"followed_artists_{self.timestamp}.csv")
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
                self.save_to_csv(top_tracks_long, f"top_tracks_all_time_{self.timestamp}.csv")
                self._mark_complete("top_tracks", self.timestamp)
                print(f"✓ Saved top tracks to CSV\n")
        else:
            print("⏭ Skipping top tracks (already exported)\n")
            top_tracks_long = []

        # Export and save top artists immediately
        if not self.resume or not self._is_complete("top_artists", self.timestamp):
            top_artists_long = self.export_top_artists("long_term")
            if top_artists_long:
                self.save_to_csv(top_artists_long, f"top_artists_all_time_{self.timestamp}.csv")
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
                "top_artists_all_time": top_artists_long
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
        print(f"  - Followed Artists: {len(followed_artists) if followed_artists else 'skipped'}")
        print(f"  - Saved Shows: {len(saved_shows) if saved_shows else 'skipped'}")
        print(f"\nAll files saved to '{self.exports_dir}/' directory")

        # Clean up progress file if export completed successfully
        if os.path.exists(self.progress_file):
            try:
                os.remove(self.progress_file)
                print(f"✓ Cleaned up progress tracking file")
            except:
                pass


def main():
    """Main execution function."""
    import sys

    # Check for resume flag
    resume = "--resume" in sys.argv

    access_token = os.getenv("SPOTIFY_ACCESS_TOKEN")
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")

    if not access_token:
        print("ERROR: SPOTIFY_ACCESS_TOKEN not found in environment variables")
        print("\nPlease create a .env file with:")
        print("SPOTIFY_ACCESS_TOKEN=your_token_here")
        print("\nSee README.md for instructions on getting your access token")
        return

    # Validate token before starting
    print("Validating access token...")
    test_response = requests.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )

    if test_response.status_code == 401:
        print("⚠ Access token is invalid or expired")

        if refresh_token and client_id and client_secret:
            print("Attempting to refresh token...")
            exporter = SpotifyExporter(access_token, client_id, client_secret, refresh_token, resume=resume)
            if exporter.refresh_access_token():
                print("✓ Token refreshed successfully, starting export...\n")
                exporter.export_all()
            else:
                print("\nERROR: Token refresh failed")
                print("Please run: python get_token.py")
        else:
            print("\nERROR: Cannot refresh token - missing credentials")
            print("Please run: python get_token.py")
    elif test_response.status_code == 200:
        user_info = test_response.json()
        print(f"✓ Token valid for user: {user_info.get('display_name', user_info.get('id'))}\n")
        exporter = SpotifyExporter(access_token, client_id, client_secret, refresh_token, resume=resume)
        exporter.export_all()
    else:
        print(f"\nERROR: Unexpected response (status {test_response.status_code})")
        print(f"Response: {test_response.text}")
        print("\nPlease run: python get_token.py")


if __name__ == "__main__":
    main()
