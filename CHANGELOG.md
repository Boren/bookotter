# Changelog

All notable changes to BookOtter will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-12-31

### Added
- Web UI with real-time sync progress via WebSocket
- Multi-Kindle device support with individual sync settings
- Scheduled sync support (cron-based)
- Auto-add feature to automatically add books to Readarr
- Docker support with multi-stage builds
- Unraid Community Applications template
- SQLite database for sync history tracking
- Path mapping for containerized Readarr instances

### Features
- **Hardcover Integration**: Sync books from "Want to Read", "Currently Reading", or "Read" lists
- **Readarr Integration**: Two-phase matching (ISBN first, fuzzy title/author fallback)
- **Kindle Transfer**: SFTP transfer over Tailscale with duplicate detection
- **Rich CLI**: Colorful terminal output with progress bars
- **Dual Logging**: Console (simplified) and file (detailed) logging

### Technical
- FastAPI backend with async support
- Vue 3 frontend with Tailwind CSS
- uv package manager for faster Docker builds
- Configurable fuzzy matching threshold
