<p align="center">
  <img src="assets/icon.png" alt="BookOtter" width="200">
</p>

# BookOtter

Automatically transfer books from your Readarr library to your Kindle based on your Hardcover reading lists.

## Features

- **Web Interface**: Modern Vue 3 dashboard for configuration, scheduling, and monitoring
- **Docker Support**: Run in a container with easy deployment
- **Scheduled Syncs**: Configure cron-like schedules via the web UI
- **Multi-Kindle Support**: Configure multiple Kindle devices and choose which to sync to
- **Real-time Progress**: Live WebSocket updates during sync operations
- **Sync History**: View past syncs and per-book results
- Fetches books from Hardcover API with configurable reading statuses:
  - "Want to Read" (default)
  - "Currently Reading" (optional)
  - "Read" (optional)
- Matches books with your Readarr library using ISBN or fuzzy title/author matching
- Transfers EPUB files to your Kindle via SSH (over Tailscale)
- Skip books already on your Kindle
- Comprehensive logging and error handling
- Dry-run mode for testing

## Requirements

- Docker (recommended) or Python 3.11+
- Hardcover account with API token
- Readarr instance with API access
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

      # Book files from Readarr - adjust to match your setup
      - /mnt/user/media/books:/books:ro

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
| `/path/to/books:/books:ro` | Book files from Readarr (read-only) |
| `~/.ssh:/root/.ssh:ro` | SSH keys for Kindle access |

### Path Mappings

Since your books are mounted differently in Docker vs Readarr, configure path mappings in `config.yaml`:

```yaml
readarr:
  path_mappings:
    - readarr_path: "/data/"        # Path as Readarr sees it
      local_path: "/books/"          # Path in BookOtter container
```

## Web Interface

The web UI provides:

### Dashboard
- Start/stop syncs manually
- Select target Kindle device
- Choose which book statuses to sync
- View real-time progress with WebSocket updates
- See latest sync statistics

### History
- View all past sync runs
- See per-book results (transferred, skipped, not found, failed)
- Filter by status
- Delete old sync records

### Schedule
- Create cron-like schedules
- Enable/disable schedules
- Choose target Kindle and book statuses per schedule
- View next scheduled run time

### Settings
- Configure Hardcover API token
- Configure Readarr connection
- Manage multiple Kindle devices
- Test all connections
- Configure matching thresholds

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

# Readarr API Settings
readarr:
  api_key: "YOUR_READARR_API_KEY"
  base_url: "http://readarr:8787"  # Or your Readarr URL
  path_mappings:
    - readarr_path: "/data/"
      local_path: "/books/"
  auto_add:
    enabled: false
    search_immediately: true

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

# Matching Settings
matching:
  use_isbn: true
  use_fuzzy: true
  fuzzy_threshold: 80

# Sync Settings
sync:
  include_statuses:
    want_to_read: true
    currently_reading: false
    read: false

# Transfer Settings
transfer:
  dry_run: false
  skip_existing: true

# Logging Settings
logging:
  log_file: "bookotter.log"
  log_level: "INFO"
  console_output: true
```

## API Endpoints

The web server exposes a REST API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/sync/start` | POST | Start a sync |
| `/api/sync/stop` | POST | Cancel running sync |
| `/api/sync/status` | GET | Get sync status |
| `/api/sync/runs` | GET | List sync history |
| `/api/sync/runs/{id}` | GET | Get sync run details |
| `/api/config` | GET/PUT | Configuration management |
| `/api/config/test/{service}` | POST | Test connection |
| `/api/kindles` | GET/POST | Kindle management |
| `/api/schedules` | GET/POST | Schedule management |
| `/api/logs` | GET | Get log entries |
| `/api/ws` | WebSocket | Real-time sync events |

## Development

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
│   ├── models/              # Database models
│   ├── api/routes/          # API endpoints
│   ├── services/            # Business logic
│   └── clients/             # API clients
├── frontend/
│   ├── src/
│   │   ├── views/           # Vue components
│   │   ├── stores/          # Pinia stores
│   │   └── router/          # Vue Router
│   └── package.json
├── data/                    # Persistent data (mounted volume)
│   ├── config.yaml
│   ├── bookotter.db
│   └── bookotter.log
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
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
- Check that Readarr is running and accessible from the container
- Ensure your Kindle is connected via Tailscale and SSH is enabled

### "No books found in Readarr"
- Books may be using different editions with different ISBNs
- Try lowering the `fuzzy_threshold` in settings
- Check if books are actually in your Readarr library

### "Transfer failed"
- Verify SSH credentials are correct
- Ensure destination path exists on Kindle
- Check that SSH keys are properly mounted in Docker
- Verify you have enough space on Kindle

### Docker networking issues
- Ensure BookOtter can reach your Readarr instance
- If using container names, ensure they're on the same Docker network
- Use host IP or hostname accessible from the container

## Security Notes

- Keep your `config.yaml` private (contains API keys)
- Use SSH keys instead of passwords when possible
- Hardcover API tokens expire January 1st each year
- The web UI has no authentication - run behind a reverse proxy or VPN
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
- [Readarr](https://readarr.com) - Book collection manager
- [Tailscale](https://tailscale.com) - Secure network connectivity
