<p align="center">
  <img src="assets/icon.png" alt="BookOtter" width="200">
</p>

# BookOtter

Self-hosted book management platform — automatically search, download, and manage your ebook library from your Hardcover reading lists.

## Features

- **Full Book Pipeline**: Hardcover sync → Prowlarr search → qBittorrent download → EPUB import with metadata → Kindle sync
- **Library Browser**: Browse your book collection with cover images, filtering, and sorting
- **Library Import**: Scan an existing books folder and match files to your library — auto-matching by embedded ID, ISBN, and title/author, with a review queue for fuzzy and unmatched files
- **Search Page**: Search for books via Prowlarr indexers and grab results for download
- **Download Queue**: Real-time download progress tracking via qBittorrent
- **Book Detail & Metadata Editor**: Edit title, author, series, and other metadata per book
- **EPUB Metadata Writing**: Automatically writes title, author, and series info into EPUB files
- **Folder Organization**: Configurable library structure — flat, by author, by series, or by author/series
- **Pipeline Automation**: Configurable status → action mapping (e.g., "want to read" triggers search + download + Kindle sync)
- **Multi-Kindle Support**: Configure multiple Kindle devices and choose which to sync to
- **Scheduled Syncs**: Configure cron-like schedules via the web UI
- **RSS Sync (Auto-Grab)**: Automatically monitor Prowlarr indexers for new releases matching your wanted books
- **Real-time Progress**: Live WebSocket updates during operations
- **Web Interface**: Modern Vue 3 dashboard for configuration, scheduling, and monitoring
- **Docker Support**: Run in a container with easy deployment
- Comprehensive logging and error handling
- Dry-run mode for testing

## Requirements

- Docker (recommended) or Python 3.11+
- Hardcover account with API token
- Prowlarr instance for book search
- qBittorrent instance for downloads
- Kindle with SSH access (jailbroken) connected via Tailscale

### Kindle Setup

Your Kindle must be **jailbroken** with an SSH server running to receive book transfers. This typically involves:

1. **Jailbreaking** your Kindle - enables running custom software
2. **Installing KUAL** (Kindle Unified Application Launcher) - app launcher for custom apps
3. **Installing USBNetwork** or similar - enables SSH access to your Kindle
4. **Setting up Tailscale** (recommended) - secure network access without port forwarding

For detailed jailbreak instructions, see the [MobileRead Wiki](https://wiki.mobileread.com/wiki/Kindle_Hacks_Information) which covers most Kindle models.

**Note:** BookOtter uses SSH/SFTP to transfer files directly to your Kindle's filesystem. The Kindle appears as a standard Linux host with root access.

## Quick Start with Docker

### 1. Clone the repository

```bash
git clone https://github.com/Boren/BookOtter.git
cd BookOtter
```

### 2. Create data directory and config

```bash
mkdir -p data
cp config.yaml.example data/config.yaml
# Edit data/config.yaml with your settings
```

### 3. Build and run

```bash
docker-compose up -d
```

### 4. Access the web UI

Open http://localhost:6887 in your browser.

## Docker Configuration

### docker-compose.yml

```yaml
version: "3.8"

services:
  bookotter:
    build: .
    container_name: bookotter
    ports:
      - "6887:6887"
    volumes:
      # Persistent data (config, database, logs)
      - ./data:/app/data

      # Book library (organized EPUBs)
      - ./library:/app/library

      # SSH keys for Kindle access
      - ~/.ssh:/root/.ssh:ro
    environment:
      - TZ=Europe/Oslo
    restart: unless-stopped
```

### Volume Mounts

| Mount | Purpose |
|-------|---------|
| `./data:/app/data` | Config file, SQLite database, and logs |
| `./library:/app/library` | Book library — organized EPUBs managed by BookOtter |
| `~/.ssh:/root/.ssh:ro` | SSH keys for Kindle access |

## Web Interface

The web UI provides:

### Library
- Browse your book collection with cover images
- Filter by status, author, series
- Sort by title, date added, author
- View book details and edit metadata

### Search
- Search for books via Prowlarr indexers
- View search results with size, seeders, indexer info
- Grab results to start downloading via qBittorrent

### Downloads
- View active download queue with real-time progress
- Cancel downloads
- Live speed and ETA from qBittorrent

### Dashboard
- Trigger Hardcover sync and Kindle sync manually
- View real-time progress with WebSocket updates
- See library statistics

### Schedule
- Create cron-like schedules
- Enable/disable schedules
- Choose target Kindle and book statuses per schedule
- View next scheduled run time

### Settings
- Configure Hardcover API token
- Configure Prowlarr and qBittorrent connections
- Manage multiple Kindle devices
- Manage root folders for library organization
- Test all connections
- Configure pipeline automation

### Logs
- View application logs in real-time
- Filter by log level
- Auto-refresh capability

## CLI Usage (without Docker)

You can still use BookOtter from the command line:

### Installation

```bash
pip install -r requirements.txt
```

### Basic Usage

```bash
# Sync "Want to Read" books
python -m backend.cli

# Dry run mode
python -m backend.cli --dry-run

# Include currently reading books
python -m backend.cli --include-currently-reading

# Custom config file
python -m backend.cli --config /path/to/config.yaml

# Skip Kindle SSH test (useful for testing matching logic)
python -m backend.cli --skip-kindle-test
```

### Running the Web Server

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 6887
```

## Configuration

### config.yaml

```yaml
# Hardcover API Settings
hardcover:
  api_token: "YOUR_API_TOKEN"  # From https://hardcover.app/account/api
  api_url: "https://api.hardcover.app/v1/graphql"

# Prowlarr (Search Indexer)
prowlarr:
  api_key: "YOUR_PROWLARR_API_KEY"
  base_url: "http://localhost:9696"

# qBittorrent (Download Client)
qbittorrent:
  base_url: "http://localhost:8080"
  username: "admin"
  password: "YOUR_QBITTORRENT_PASSWORD"
  category: "books"

# Kindle Devices (multiple supported)
kindles:
  - id: "main"
    name: "My Kindle"
    hostname: "kindle.tailnet"
    port: 22
    username: "root"
    password: ""
    ssh_key_path: "/root/.ssh/id_rsa"
    destination_path: "/mnt/us/books/"
  - id: "backup"
    name: "Backup Kindle"
    hostname: "kindle2.tailnet"
    # ...

# Library Settings
library:
  root_folders: []          # Managed via web UI
  download_path: ""         # Display only — qBittorrent manages actual paths

# Pipeline (Automation)
pipeline:
  enabled: true
  search_on_add: true       # Auto-search when book added
  import_on_complete: true  # Auto-import when download completes
  kindle_sync_on_import: true  # Auto-send imports on synced shelves to Kindle
  status_actions:
    want_to_read:
      download: true
    currently_reading:
      download: true
    read:
      download: true

# RSS Sync (Auto-Grab)
rss:
  enabled: false            # Enable background RSS monitoring
  cron_expression: "*/15 * * * *" # How often to poll indexers
  max_age_days: 3           # Only consider items newer than this
  limit: 100                # Max items to fetch per indexer per poll

# Matching Settings
matching:
  use_isbn: true
  use_fuzzy: true
  fuzzy_threshold: 80

# Sync Settings (which Hardcover shelves are imported into the library)
sync:
  include_statuses:
    want_to_read: true
    currently_reading: false
    read: false

# Transfer Settings (Kindle mirror)
transfer:
  dry_run: false               # Report what would be sent/deleted without doing it
  folder_organization: "flat"  # flat, author, series, author_series
  sync_shelves:                # Hardcover shelves mirrored to the Kindle
    want_to_read: true
    currently_reading: true
    read: false
  cleanup_enabled: true        # Remove device books not on synced shelves or pinned
  cleanup_sdr_folders: true    # Also remove .sdr reading data for deleted books
  cleanup_protected_paths: []  # Device paths cleanup must never touch

# Logging Settings
logging:
  log_file: "bookotter.log"
  log_level: "INFO"
  console_output: true
```

### Pipeline Configuration

The pipeline automates the full book lifecycle. When a Hardcover sync finds books matching configured statuses, the pipeline can automatically:

1. **Search** Prowlarr for available downloads
2. **Download** via qBittorrent with the configured category
3. **Import** completed downloads into the library with EPUB metadata
4. **Sync** imported books to your Kindle (only books on shelves enabled in `transfer.sync_shelves`, plus manually pinned books)

Control which statuses trigger downloads via `pipeline.status_actions`. Which books reach the Kindle is governed separately by `transfer.sync_shelves`: the Kindle mirrors those shelves — a sync sends missing shelf books and, when `cleanup_enabled` is on, removes everything else from the device (books sent manually via "Send to Kindle" are pinned and kept).

### RSS Sync (Auto-Grab)

The RSS sync feature periodically polls your Prowlarr indexers for new releases. If a release matches a book in your library with a `WANTED` or `MISSING` status, it is automatically grabbed for download.

- **First-run behavior**: On the very first poll, BookOtter marks all current RSS items as "seen" **without grabbing them**. This prevents an accidental flood of old downloads. To backfill existing books, use the manual search workflow.
- **Matching**: Uses fuzzy title and author matching (respects `matching.fuzzy_threshold`).
- **Exclusions**: Currently ignores Usenet and audiobooks.
- **Events**: Emits `rss_sync_started`, `rss_sync_completed`, `rss_sync_failed`, `rss_indexer_polled`, `rss_match_found`, and `rss_grabbed`.

### Folder Organization

The `transfer.folder_organization` setting controls how books are organized in your library and on Kindle:

| Mode | Structure |
|------|-----------|
| `flat` | All books in root folder |
| `author` | `Author Name/book.epub` |
| `series` | `Series Name/book.epub` |
| `author_series` | `Author Name/Series Name/book.epub` |

## API Endpoints

The web server exposes a REST API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/library/books` | GET | List books with filtering/pagination |
| `/api/library/books/{id}` | GET | Get book details |
| `/api/library/books` | POST | Add a book |
| `/api/library/books/{id}` | PUT | Update book metadata |
| `/api/library/books/{id}` | DELETE | Delete a book |
| `/api/search` | GET | Search Prowlarr indexers |
| `/api/search/grab` | POST | Grab a search result for download |
| `/api/search/auto/{book_id}` | POST | Auto-search for a book |
| `/api/downloads` | GET | List active downloads |
| `/api/downloads/{id}` | DELETE | Cancel a download |
| `/api/root-folders` | GET/POST | Root folder management |
| `/api/sync/status` | GET | Get sync status |
| `/api/sync/hardcover` | POST | Trigger Hardcover sync |
| `/api/sync/kindle` | POST | Trigger Kindle sync |
| `/prowlarr/test` | POST | Test Prowlarr connection |
| `/qbittorrent/test` | POST | Test qBittorrent connection |
| `/prowlarr/indexers` | GET | List Prowlarr indexers |
| `/api/config` | GET/PUT | Configuration management |
| `/api/kindles` | GET/POST | Kindle management |
| `/api/schedules` | GET/POST | Schedule management |
| `/api/logs` | GET | Get log entries |
| `/api/ws` | WebSocket | Real-time events |

## Development

### Local Database Setup

After pulling library-scanner changes, delete `data/bookotter.db` to rebuild the schema with the new constraints.

### Backend Development

```bash
# Install dependencies (recommended: use uv for faster installs)
uv pip install -r pyproject.toml

# Or with pip
pip install -r requirements.txt

# Run development server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 6887
```

### Frontend Development

```bash
cd frontend

# Install dependencies
pnpm install

# Run development server (proxies API to localhost:6887)
pnpm dev

# Build for production
pnpm build
```

### Project Structure

```
bookotter/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── config.py            # Configuration management
│   ├── database.py          # SQLAlchemy setup
│   ├── models/              # Database models (books, downloads, etc.)
│   ├── api/routes/          # API endpoints
│   │   ├── library.py       # Book CRUD and browsing
│   │   ├── search.py        # Prowlarr search and grab
│   │   ├── downloads.py     # Download queue
│   │   ├── sync.py          # Hardcover and Kindle sync
│   │   ├── services.py      # Connection tests (Prowlarr, qBittorrent)
│   │   ├── root_folders.py  # Root folder management
│   │   └── ...              # config, kindles, schedules, logs
│   ├── services/            # Business logic
│   │   ├── pipeline_service.py      # Full automation pipeline
│   │   ├── pipeline_states.py       # Book state machine
│   │   ├── hardcover_sync_service.py # Hardcover sync
│   │   ├── search_service.py        # Search orchestration
│   │   ├── download_service.py      # Download management
│   │   ├── import_service.py        # EPUB import with metadata
│   │   ├── epub_service.py          # EPUB metadata read/write
│   │   └── ...              # scheduler, websocket manager
│   └── clients/             # External service clients
│       ├── hardcover_client.py    # Hardcover GraphQL API
│       ├── prowlarr_client.py     # Prowlarr REST API
│       ├── qbittorrent_client.py  # qBittorrent Web API
│       └── kindle_client.py       # Kindle SSH/SFTP
├── frontend/
│   ├── src/
│   │   ├── views/           # Vue page components
│   │   ├── stores/          # Pinia stores
│   │   └── router/          # Vue Router
│   └── package.json
├── data/                    # Persistent data (mounted volume)
│   ├── config.yaml
│   ├── bookotter.db
│   └── bookotter.log
├── Dockerfile
├── docker-compose.yml
└── config.yaml.example
```

## Development Workflow

### Branching Strategy

- **dev**: Development branch for feature work and testing
- **main**: Production-ready code, releases are tagged from here

```
feature → dev → PR → main → git tag v1.x.x → Release
```

### Docker Images

Docker images are automatically built and pushed to GitHub Container Registry:

| Event | Image Tags |
|-------|------------|
| Push to `dev` | `ghcr.io/boren/bookotter:dev` |
| Push to `main` | `ghcr.io/boren/bookotter:main` |
| Tag `v1.2.3` | `:1.2.3`, `:1.2`, `:1`, `:latest` |

### CI Checks

All pushes and PRs run automated checks:
- **Backend**: Python linting with [Ruff](https://docs.astral.sh/ruff/)
- **Frontend**: TypeScript type-checking and build verification

### Creating a Release

1. Merge your changes from `dev` to `main`
2. Create and push a semantic version tag:
   ```bash
   git tag v1.0.0
   git push --tags
   ```
3. GitHub Actions will automatically:
   - Build and push Docker images with version tags
   - Create a GitHub Release with auto-generated changelog

### Conventional Commits

Use [conventional commits](https://www.conventionalcommits.org/) for automatic changelog generation:
- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation changes
- `refactor:` Code refactoring
- `test:` Adding tests
- `chore:` Maintenance tasks

## Troubleshooting

### "Connection test failed"
- Verify your API tokens and keys are correct
- Check that Prowlarr and qBittorrent are running and accessible from the container
- Ensure your Kindle is connected via Tailscale and SSH is enabled

### "Prowlarr search returned no results"
- Verify your Prowlarr instance has book indexers configured
- Test the search directly in Prowlarr's web UI to confirm indexers work
- Check that the Prowlarr API key is correct in settings

### "qBittorrent connection failed"
- Verify qBittorrent Web UI is enabled (Options → Web UI)
- Check username and password are correct
- If running in Docker, ensure BookOtter can reach qBittorrent's network address

### "EPUB import failed"
- Ensure the downloaded file is a valid EPUB
- Check that the library root folder exists and is writable
- Verify volume mounts in Docker are correct

### "Transfer failed"
- Verify SSH credentials are correct
- Ensure destination path exists on Kindle
- Check that SSH keys are properly mounted in Docker
- Verify you have enough space on Kindle

### Docker networking issues
- Ensure BookOtter can reach Prowlarr and qBittorrent instances
- If using container names, ensure they're on the same Docker network
- Use host IP or hostname accessible from the container

## Security Notes

- Keep your `config.yaml` private — it contains API keys and passwords
- Prowlarr API key and qBittorrent password are stored in plain text in the config file
- Use SSH keys instead of passwords for Kindle connections when possible
- Hardcover API tokens expire January 1st each year
- The web UI has no authentication — run behind a reverse proxy or VPN
- Never commit `config.yaml` to version control

### SSH Host Key Verification

BookOtter uses `AutoAddPolicy` for SSH connections, which automatically accepts host keys on first connection. This is acceptable for personal use on a trusted network (e.g., Tailscale VPN), but means:

- The first connection to a Kindle will trust its host key without verification
- You should ensure your Tailscale network is properly secured
- For high-security environments, consider pre-populating `~/.ssh/known_hosts`

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Hardcover](https://hardcover.app) - Book tracking platform
- [Prowlarr](https://prowlarr.com) - Indexer manager/proxy
- [qBittorrent](https://www.qbittorrent.org) - BitTorrent client
- [Tailscale](https://tailscale.com) - Secure network connectivity
