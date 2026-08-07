#!/usr/bin/env python3
"""
BookOtter CLI - Command line interface using backend services.

Usage:
    python -m backend.cli [--dry-run] [--config CONFIG] [--skip-ereader-test]
                          [--include-currently-reading] [--include-read]
"""

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session

from backend.clients.hardcover_client import HardcoverClient
from backend.clients.ereader_client import EreaderClient
from backend.config import load_config
from backend.database import DATA_DIR, SessionLocal
from backend.models.book import Book, BookStatus
from backend.utils.failure import _append_failure_history


class CLIRunner:
    """CLI wrapper for SyncService with Rich terminal output."""

    def __init__(
        self,
        config_path: str = "config.yaml",
        include_currently_reading: bool = False,
        include_read: bool = False,
    ):
        """
        Initialize the CLI runner.

        Args:
            config_path: Path to configuration file
            include_currently_reading: Include books with 'Currently Reading' status
            include_read: Include books with 'Read' status
        """
        # Set config path environment variable for backend.config
        if config_path != "config.yaml":
            os.environ["BOOKOTTER_CONFIG"] = config_path

        self.config = load_config()
        self.console = Console()
        self._setup_logging()

        # Build list of status IDs to sync
        self.status_ids = [1]  # Always include "Want to Read"

        sync_config = self.config.get("sync", {}).get("include_statuses", {})

        if include_currently_reading or sync_config.get("currently_reading", False):
            self.status_ids.append(2)

        if include_read or sync_config.get("read", False):
            self.status_ids.append(3)

        # Progress tracking
        self._progress = None
        self._task_id = None
        self._current_book = ""

        # Statistics
        self.stats = {
            "total_books": 0,
            "matched": 0,
            "transferred": 0,
            "failed": 0,
            "not_found": 0,
            "skipped": 0,
            "cleaned_up": 0,
        }

    def _setup_logging(self):
        """Configure logging with dual handlers: file + console."""
        log_config = self.config.get("logging", {})
        log_level = getattr(logging, log_config.get("log_level", "INFO"))

        # Create file handler
        file_handler = logging.FileHandler(log_config.get("log_file", "bookotter.log"))
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_formatter)

        # Configure root logger with file handler only
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.addHandler(file_handler)

        # Suppress verbose third-party logs
        logging.getLogger("paramiko").setLevel(logging.WARNING)

        self.logger = logging.getLogger(__name__)

    def _console_info(self, message: str, emoji: str = "ℹ"):
        """Display info message to console and log to file."""
        self.console.print(f"[cyan]{emoji}[/cyan] {message}")
        self.logger.info(message)

    def _console_success(self, message: str, emoji: str = "✓"):
        """Display success message to console and log to file."""
        self.console.print(f"[green]{emoji}[/green] {message}")
        self.logger.info(message)

    def _console_warning(self, message: str, emoji: str = "⚠"):
        """Display warning message to console and log to file."""
        self.console.print(f"[yellow]{emoji}[/yellow] {message}")
        self.logger.warning(message)

    def _console_error(self, message: str, emoji: str = "✗"):
        """Display error message to console and log to file."""
        self.console.print(f"[red]{emoji}[/red] {message}")
        self.logger.error(message)

    def test_connections(self, skip_ereader: bool = False) -> tuple[bool, bool]:
        """
        Test connections to all services.

        Returns:
            Tuple of (all_passed, ereader_unreachable)
        """
        self.console.print("\n[bold cyan]Testing connections...[/bold cyan]")
        self.logger.info("Testing connections to all services")

        hardcover_config = self.config.get("hardcover", {})

        # Test Hardcover
        hardcover = HardcoverClient(
            api_token=hardcover_config.get("api_token", ""),
            api_url=hardcover_config.get("api_url", "https://api.hardcover.app/v1/graphql"),
        )
        if not hardcover.test_connection():
            self._console_error("Failed to connect to Hardcover API")
            return (False, False)
        self._console_success("Connected to Hardcover")

        # Test E-reader SSH
        if not skip_ereader:
            ereaders = self.config.get("ereaders", [])
            ereader_config = ereaders[0] if ereaders else None

            if ereader_config:
                try:
                    ereader_client = EreaderClient.from_config(ereader_config)
                    if ereader_client.test_connection():
                        self._console_success("Connected to E-reader via SSH")
                    else:
                        return (False, True)
                except Exception as e:
                    self._console_error(f"E-reader SSH connection failed: {e}")
                    return (False, True)
            else:
                self._console_warning("No E-reader configured")
        else:
            self._console_info("Skipping E-reader SSH connection test", emoji="⏭")

        self._console_success("All connection tests passed!")
        return (True, False)

    async def _handle_event(self, event: str, data: Any):
        """Handle events from the sync service."""
        if event == "sync_started":
            self.console.print()
            self.console.rule("[bold cyan]Starting BookOtter[/bold cyan]", style="cyan")
            self.console.print()

            status_names = {1: "Want to Read", 2: "Currently Reading", 3: "Read"}
            status_labels = [status_names.get(sid, str(sid)) for sid in self.status_ids]
            self.console.print(f"[dim]Syncing books with statuses: {', '.join(status_labels)}[/dim]\n")

        elif event == "books_fetched":
            self.stats["total_books"] = data.get("total_books", 0)

        elif event == "book_progress":
            book = data.get("book", {})
            current = data.get("current", 0)
            data.get("total", 0)
            title = book.get("title", "Unknown")
            author = book.get("author", "")
            status = book.get("status", "")

            if self._progress and self._task_id is not None:
                self._progress.update(self._task_id, completed=current - 1, current_book=f"{title} by {author}")

        elif event == "book_completed":
            book = data.get("book", {})
            title = book.get("title", "Unknown")
            status = book.get("status", "")
            file_size = book.get("file_size", 0)
            error_message = book.get("error_message", "")

            # Print status based on result
            if status == "not_found":
                self.console.print(f"   [yellow]⚠[/yellow] Not found: {title}")
                self.stats["not_found"] += 1
            elif status == "matched_no_files":
                self.console.print(f"   [yellow]⚠[/yellow] No EPUB files: {title}")
            elif status == "add_failed":
                self.console.print(f"   [red]✗[/red] Failed to add: {title}")
            elif status == "transferred":
                size_str = self._format_size(file_size)
                self.console.print(f"   [green]✓[/green] Transferred: {title} ({size_str})")
                self.stats["transferred"] += 1
                self.stats["matched"] += 1
            elif status == "skipped":
                self.console.print(f"   [dim]⏭ Skipped (already on E-reader): {title}[/dim]")
                self.stats["skipped"] += 1
                self.stats["matched"] += 1
            elif status == "failed":
                self.console.print(f"   [red]✗[/red] Failed: {title} - {error_message}")
                self.stats["failed"] += 1
            elif status == "dry_run":
                self.console.print(f"   [dim][DRY RUN] Would transfer: {title}[/dim]")
                self.stats["transferred"] += 1
                self.stats["matched"] += 1

            if self._progress and self._task_id is not None:
                self._progress.advance(self._task_id)

        elif event == "transfer_progress":
            # Transfer progress is shown via the progress bar
            pass

        elif event == "cleanup_started":
            self.console.print("\n[cyan]Starting cleanup phase...[/cyan]")

        elif event == "cleanup_completed":
            cleaned = data.get("cleaned_up", 0)
            self.stats["cleaned_up"] = cleaned
            if cleaned > 0:
                self.console.print(f"   [green]✓[/green] Removed {cleaned} orphaned books")

        elif event == "sync_completed":
            stats = data.get("stats", {})
            self.stats.update(stats)

    def _format_size(self, size_bytes: int) -> str:
        """Format file size for display."""
        if size_bytes == 0:
            return "0 B"
        size_kb = size_bytes / 1024
        if size_kb > 1024:
            return f"{size_kb / 1024:.1f} MB"
        return f"{size_kb:.0f} KB"

    def print_summary(self):
        """Print summary statistics."""
        status_names = {1: "Want to Read", 2: "Currently Reading", 3: "Read"}
        status_labels = [status_names.get(sid, f"Unknown ({sid})") for sid in self.status_ids]
        status_str = ", ".join(status_labels)

        # Log to file
        self.logger.info("\n" + "=" * 80)
        self.logger.info("BookOtter Summary")
        self.logger.info("=" * 80)
        self.logger.info(f"Synced statuses:               {status_str}")
        self.logger.info(f"Total books fetched:           {self.stats['total_books']}")
        self.logger.info(f"Books matched:                 {self.stats['matched']}")
        self.logger.info(f"Books not found:               {self.stats['not_found']}")
        self.logger.info(f"Successfully transferred:      {self.stats['transferred']}")
        self.logger.info(f"Skipped (already on E-reader):   {self.stats['skipped']}")
        self.logger.info(f"Transfer failures:             {self.stats['failed']}")
        if self.stats.get("cleaned_up", 0) > 0:
            self.logger.info(f"Cleaned up:                    {self.stats['cleaned_up']}")
        self.logger.info("=" * 80)

        # Display to console
        self.console.print()
        self.console.rule("[bold cyan]Summary[/bold cyan]", style="cyan")
        self.console.print()

        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        table.add_column("Category", style="cyan", width=30)
        table.add_column("Count", justify="right", style="bold")

        table.add_row("Synced statuses", status_str)
        table.add_row("Total books", str(self.stats["total_books"]))
        table.add_row("Matched", f"[green]{self.stats['matched']}[/green]")
        table.add_row(
            "Not found", f"[yellow]{self.stats['not_found']}[/yellow]" if self.stats["not_found"] > 0 else "0"
        )

        table.add_row("Successfully transferred", f"[green]{self.stats['transferred']}[/green]")
        table.add_row(
            "Skipped (already on E-reader)", f"[dim]{self.stats['skipped']}[/dim]" if self.stats["skipped"] > 0 else "0"
        )
        table.add_row("Transfer failures", f"[red]{self.stats['failed']}[/red]" if self.stats["failed"] > 0 else "0")

        if self.stats.get("cleaned_up", 0) > 0:
            table.add_row("Cleaned up", f"[yellow]{self.stats['cleaned_up']}[/yellow]")

        self.console.print(table)
        self.console.print()

    async def run(self, skip_ereader_test: bool = False, dry_run: bool = False):
        """Run the complete sync process."""
        try:
            # Test connections first
            all_passed, ereader_unreachable = self.test_connections(skip_ereader=skip_ereader_test)

            if not all_passed:
                if ereader_unreachable:
                    skip_if_unreachable = self.config.get("ereader", {}).get("skip_if_unreachable", False)
                    # Check ereaders list format too
                    ereaders = self.config.get("ereaders", [])
                    if ereaders and ereaders[0].get("skip_if_unreachable", False):
                        skip_if_unreachable = True

                    if skip_if_unreachable:
                        self.console.print("[yellow]⚠[/yellow] E-reader unreachable - skipping this run")
                        self.logger.info("E-reader unreachable, skipping run due to skip_if_unreachable setting")
                        sys.exit(0)
                    else:
                        self._console_error("Failed to connect to E-reader via SSH")
                        self.logger.error("Connection tests failed. Please check your configuration.")
                        sys.exit(1)
                else:
                    self.logger.error("Connection tests failed. Please check your configuration.")
                    sys.exit(1)

            self._console_info("CLI sync is no longer supported. Use the web UI or API instead.")
            self._console_info("  Hardcover sync: POST /api/sync/hardcover")
            self._console_info("  E-reader sync:    POST /api/sync/ereader")
            sys.exit(0)

        except KeyboardInterrupt:
            self.logger.info("\nProcess interrupted by user")
            self.print_summary()
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}", exc_info=True)
            sys.exit(1)


def force_retry_book(book_id: int, db: Session) -> int:
    """
    Force retry a failed or permanently failed book.

    Args:
        book_id: ID of the book to retry
        db: Database session

    Returns:
        Exit code: 0 on success, 1 on book-not-found, 2 on not-retryable-state
    """
    console = Console()

    book = db.get(Book, book_id)
    if book is None:
        console.print(f"[red]Book {book_id} not found[/red]")
        return 1

    retryable = {BookStatus.FAILED.value, BookStatus.PERMANENT_FAILED.value}
    if book.status not in retryable:
        console.print(f"[red]Book {book_id} is not retryable (status: {book.status})[/red]")
        return 2

    previous = book.status
    if book.failure_reason:
        _append_failure_history(book, book.failure_reason)
    _append_failure_history(book, "MANUAL_RETRY")
    book.status = BookStatus.WANTED.value
    book.retry_count = 0
    book.failure_reason = None
    book.low_confidence = False
    db.commit()

    console.print(f"[green]Book {book_id} reset from {previous} → WANTED[/green]")
    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sync Hardcover 'want to read' books to E-reader")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # force-retry subcommand
    force_retry_parser = subparsers.add_parser("force-retry", help="Force retry a failed book")
    force_retry_parser.add_argument("book_id", type=int, help="Book ID to retry")

    # migrate-to-ereader subcommand
    migrate_parser = subparsers.add_parser(
        "migrate-to-ereader", help="One-shot rename of legacy kindle data/config to ereader"
    )
    migrate_parser.add_argument("--dry-run", action="store_true", help="Report actions without changing anything")
    migrate_parser.add_argument("--force", action="store_true", help="Overwrite existing .bak-ereader backups")

    # Legacy sync command (default)
    parser.add_argument("--config", default="config.yaml", help="Path to configuration file (default: config.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate transfers without actually copying files")
    parser.add_argument("--skip-ereader-test", action="store_true", help="Skip E-reader SSH connection test")
    parser.add_argument(
        "--include-currently-reading", action="store_true", help="Include books with 'Currently Reading' status"
    )
    parser.add_argument("--include-read", action="store_true", help="Include books with 'Read' status")

    args = parser.parse_args()

    # Handle force-retry subcommand
    if args.command == "migrate-to-ereader":
        from pathlib import Path

        from backend.services.ereader_migration import run_migration

        report = run_migration(Path(DATA_DIR), dry_run=args.dry_run, force=args.force)
        if report.already_migrated:
            print("Already migrated — nothing to do.")
        else:
            prefix = "[dry-run] would " if args.dry_run else ""
            for action in report.actions:
                print(f"{prefix}{action}")
        sys.exit(0)

    if args.command == "force-retry":
        db = SessionLocal()
        try:
            exit_code = force_retry_book(args.book_id, db)
            sys.exit(exit_code)
        finally:
            db.close()

    # Default: run sync
    runner = CLIRunner(
        config_path=args.config,
        include_currently_reading=args.include_currently_reading,
        include_read=args.include_read,
    )

    # Run sync
    asyncio.run(
        runner.run(
            skip_ereader_test=args.skip_ereader_test,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
