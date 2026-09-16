# 🚪 Spotify Exit

**Your complete Spotify data export tool for a smooth migration to any music service.**

A Python script to export all your Spotify data before leaving the platform. Exports playlists, saved tracks, albums, followed artists, podcasts, and listening statistics with migration-friendly formats (ISRC/UPC codes included).

## Features

- **Complete Data Export**: All your Spotify library data in one go
  - Saved tracks with metadata (ISRC codes for matching on other platforms)
  - All playlists with complete track listings
  - Saved albums with UPC codes
  - Followed artists
  - Saved podcasts/shows
  - Top tracks and artists (all-time stats)

- **Incremental Saving**: Data is saved as it's fetched
  - Each playlist is saved immediately after being fetched
  - Main categories (tracks, albums, artists) saved after completion
  - No data loss if the script is interrupted
  - Resume-friendly for large libraries

- **Multiple Export Formats**:
  - Comprehensive JSON file with all data
  - Individual CSV files for each category
  - Separate CSV file for each playlist

- **Migration-Friendly**:
  - Includes ISRC codes for tracks (universal song identifiers)
  - Includes UPC codes for albums
  - Spotify URIs for reference
  - External URLs for each item

- **Robust Error Handling**:
  - Automatic token refresh on expiration
  - Graceful handling of missing/null metadata
  - Network timeout recovery
  - Detailed error messages

## Setup

### 1. Install Dependencies

```bash
uv sync
```

### 2. Get Spotify API Credentials

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app (or use an existing one)
3. In app settings, add `http://127.0.0.1:8888/callback` to "Redirect URIs"

   > **Use the IP, not `localhost`.** Spotify rejects `localhost` as a redirect
   > URI host and requires an explicit loopback address. The dashboard may
   > display your entry back as `localhost` after you refresh the page — it was
   > still saved correctly. Navigate away and back to confirm.

4. Copy your Client ID and Client Secret into a `.env` file:
   ```bash
   cp .env.example .env
   # then edit .env and fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
   ```
5. Run the token generator:
   ```bash
   uv run get_token.py
   ```
6. Follow the browser prompts to authorize
7. Your access and refresh tokens are saved to `.env` automatically

Port 8888 already taken? Set `SPOTIFY_REDIRECT_PORT` in `.env` and register the
matching URI in the dashboard — `get_token.py` prints the exact URI it will use
each time it runs, so copy it from there.

### 3. Required API Scopes

`get_token.py` requests these automatically and prints them at startup — the
`SCOPES` list in `spotify_config.py` is authoritative if this list ever drifts:

- `user-library-read` - Saved tracks and albums
- `user-follow-read` - Followed artists
- `user-top-read` - Top tracks and artists
- `playlist-read-private` - Private playlists
- `playlist-read-collaborative` - Collaborative playlists
- `user-read-email` - User profile
- `user-read-private` - User profile details

## Usage

### Basic Export

```bash
uv run spotify_export.py
```

This will export all your data to the `exports/` directory.

### Resume Mode

If your export gets interrupted (network issues, script crash, etc.), you can resume where you left off:

```bash
uv run spotify_export.py --resume
```

**How resume works:**
- The script tracks progress in a hidden `.export_progress.json` file
- Already-exported playlists are skipped automatically
- Completed sections (tracks, albums, artists) are skipped
- Only fetches data that hasn't been exported yet
- Progress file is cleaned up after successful completion

**When to use resume:**
- Script crashed during playlist export
- Network timeout interrupted the export
- You manually stopped the script (Ctrl+C)
- Token expired mid-export and you need to restart

**Note:** Resume uses the same timestamp from the original export, so all files will have matching timestamps.

### Output Files

The script creates:

```
exports/
├── spotify_full_export_YYYYMMDD_HHMMSS.json    # Complete data dump
├── saved_tracks_YYYYMMDD_HHMMSS.csv            # All saved songs
├── saved_albums_YYYYMMDD_HHMMSS.csv            # All saved albums
├── followed_artists_YYYYMMDD_HHMMSS.csv        # Followed artists
├── saved_shows_YYYYMMDD_HHMMSS.csv             # Podcasts
├── top_tracks_all_time_YYYYMMDD_HHMMSS.csv     # Most played tracks
├── top_artists_all_time_YYYYMMDD_HHMMSS.csv    # Most played artists
└── playlist_[NAME]_YYYYMMDD_HHMMSS.csv         # Individual playlists
```

### Using the Data for Migration

**For Apple Music / YouTube Music / Tidal:**
- Use ISRC codes from `saved_tracks.csv` to match songs
- Many services have playlist import tools that accept CSV files

**For self-hosted solutions (Plex, Jellyfin):**
- Use artist/album/track names to match with your local library
- ISRC codes can help with automatic matching tools

**For playlist backup:**
- Each playlist is exported as a separate CSV
- Includes track names, artists, albums, and Spotify URLs

## Data Included

### User Profile
- Display name, email, country
- Account type (free/premium)
- Follower count

### Saved Tracks
- Track name, artist(s), album
- Duration, release date
- ISRC code (International Standard Recording Code)
- Spotify URL and URI

### Playlists
- Playlist name, description, owner
- Public/private/collaborative status
- Complete track listings with metadata

### Saved Albums
- Album name, artist(s)
- Release date, track count
- UPC code (Universal Product Code)
- Spotify URL and URI

### Followed Artists
- Artist name, genres
- Popularity score, follower count
- Spotify URL and URI

### Podcasts/Shows
- Show name, publisher
- Description, episode count
- Date added

### Listening Stats
- Top 50 tracks (all-time)
- Top 50 artists (all-time)

## Limitations

- **Rate Limiting**: The script includes small delays to avoid hitting API rate limits
- **Token Expiry**: Access tokens expire after 1 hour; the script refreshes them automatically using the refresh token saved in `.env`
- **Listening History**: Spotify doesn't provide complete listening history via API (only top items)
- **Podcast Episodes**: Individual episode saves are not easily accessible via current API

## Troubleshooting

### "INVALID_CLIENT: Invalid redirect URI"

The redirect URI in the Spotify dashboard must match `http://127.0.0.1:8888/callback`
exactly. Spotify no longer accepts `localhost` as the host — use the IP. If the
dashboard shows `localhost` after a refresh, navigate away and back; the value you
entered was saved.

### "Access token expired"
The script refreshes expired tokens automatically. If the refresh fails (for
example, you revoked the app's access), run `uv run get_token.py` again.

### "Rate limit exceeded"
Wait a few minutes and try again. The script includes rate limiting, but Spotify may still throttle requests.

### Missing playlists
Make sure your token includes the `playlist-read-private` scope.

### Empty exports
Verify your token has all required scopes and hasn't expired.

## Privacy & Security

- Your access token provides full read access to your Spotify account
- Never share your `.env` file or tokens publicly
- Tokens expire automatically for security
- This script only reads data, it cannot modify your Spotify account

## License

Free to use and modify for personal use.

## Acknowledgments

Built using the [Spotify Web API](https://developer.spotify.com/documentation/web-api/).
