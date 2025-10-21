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
pip install -r requirements.txt
```

### 2. Get Spotify API Credentials

You have two options:

#### Option A: Quick Method (Web Console)

1. Go to the [Spotify Web API Console](https://developer.spotify.com/console/get-current-user/)
2. Click "Get Token"
3. Select all required scopes (see below)
4. Copy the generated token
5. Create `.env` file with: `SPOTIFY_ACCESS_TOKEN=your_token_here`

**Note**: Tokens from the console expire in 1 hour.

#### Option B: OAuth Flow (Recommended)

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app (or use an existing one)
3. In app settings, add `http://localhost:8888/callback` to "Redirect URIs"
4. Copy your Client ID and Client Secret
5. Set environment variables:
   ```bash
   export SPOTIFY_CLIENT_ID='your_client_id'
   export SPOTIFY_CLIENT_SECRET='your_client_secret'
   ```
6. Run the token generator:
   ```bash
   python get_token.py
   ```
7. Follow the browser prompts to authorize
8. Token will be automatically saved to `.env`

### 3. Required API Scopes

The following scopes are needed for complete data export:

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
python spotify_export.py
```

This will export all your data to the `exports/` directory.

### Resume Mode

If your export gets interrupted (network issues, script crash, etc.), you can resume where you left off:

```bash
python spotify_export.py --resume
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
- **Token Expiry**: Access tokens expire after 1 hour (console method) or when refresh token is used
- **Listening History**: Spotify doesn't provide complete listening history via API (only top items)
- **Podcast Episodes**: Individual episode saves are not easily accessible via current API

## Troubleshooting

### "Access token expired"
Run `python get_token.py` again to get a fresh token.

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
