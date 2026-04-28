# Changelog

All notable changes to BookOtter will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- feat: search UX uplift — interactive search, status badges, wanted page, blocklist
  - Fixed WebSocket broadcasting: all 11 pipeline events now fire in real time
  - Interactive search table with sortable columns (Age, Title, Indexer, Size, Peers, Rejections)
  - Structured rejection system: audiobook, no-seeder, size bounds, blocklist, format checks
  - Automatic Search vs Interactive Search buttons on book detail pages
  - `MISSING` book status for new books from Hardcover sync
  - Wanted page listing all missing books with bulk Search All action
  - Global blocklist: permanently reject releases from search results
  - StatusBadge component showing pipeline state on library cards and book detail
  - Startup backfill converting idle WANTED books to MISSING status

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
