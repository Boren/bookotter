"""Tests for WebSocket event broadcasting integration."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from backend.clients.qbittorrent_client import TorrentState
from backend.models.book import Book, BookStatus, Download, DownloadStatus, FolderOrganization, RootFolder
from backend.services.download_service import DownloadService
from backend.services.import_service import BookImportError, ImportService
from backend.services.pipeline_service import PipelineService
from backend.services.websocket_manager import WebSocketManager
from tests.helpers import create_test_book, create_test_epub


def _session_factory(db_session):
    return lambda: db_session


def _fresh_book(db_session, book_id: int) -> Book:
    db_session.expire_all()
    book = db_session.get(Book, book_id)
    assert book is not None
    return book


def _fresh_download(db_session, download_id: int) -> Download:
    db_session.expire_all()
    download = db_session.get(Download, download_id)
    assert download is not None
    return download


def _event_payloads(ws_manager: MagicMock, event_name: str) -> list[dict]:
    return [call.args[1] for call in ws_manager.broadcast_sync.call_args_list if call.args[0] == event_name]


def _book_status(book: Book) -> str:
    return cast(str, book.status)


def _download_status(download: Download) -> str:
    return cast(str, download.status)


def _create_download(
    db_session,
    book: Book,
    *,
    torrent_hash: str = "hash-1",
    status: str = DownloadStatus.QUEUED.value,
    file_path: str | None = None,
) -> Download:
    download = Download(
        book_id=book.id,
        torrent_hash=torrent_hash,
        torrent_name=f"{book.title}.epub",
        indexer_name="TestIndexer",
        download_url="https://example.com/torrent",
        size=5_000_000,
        seeders=10,
        status=status,
        file_path=file_path,
    )
    db_session.add(download)
    db_session.commit()
    db_session.refresh(download)
    return download


def _create_root_folder(db_session, path: Path) -> RootFolder:
    root_folder = RootFolder(
        name="Test Library",
        path=str(path),
        folder_organization=FolderOrganization.FLAT.value,
        created_at=datetime.utcnow(),
    )
    db_session.add(root_folder)
    db_session.commit()
    db_session.refresh(root_folder)
    return root_folder


class TestBroadcastSync:
    def test_broadcast_sync_with_running_loop(self):
        manager = WebSocketManager()
        loop = MagicMock()

        with patch("backend.services.websocket_manager.asyncio.get_running_loop", return_value=loop):
            manager.broadcast_sync("download_progress", {"download_id": 1})

        loop.create_task.assert_called_once()
        coroutine = loop.create_task.call_args.args[0]
        assert asyncio.iscoroutine(coroutine)
        coroutine.close()

    def test_broadcast_sync_no_loop(self):
        manager = WebSocketManager()

        with patch("backend.services.websocket_manager.asyncio.get_running_loop", side_effect=RuntimeError):
            result = manager.broadcast_sync("download_progress", {"download_id": 1})

        assert result is None


class TestPipelineEvents:
    def test_pipeline_emits_status_and_stage_events_across_happy_path(self, db_session):
        ws_manager = MagicMock()
        search_service = MagicMock()
        search_service.search_book.return_value = [
            {
                "guid": "guid-1",
                "title": "Dune Release.epub",
                "indexer": "IndexerOne",
                "seeders": 42,
                "size": 5_000_000,
                "download_url": "https://example.com/download/1",
                "magnet_url": "magnet:?xt=urn:btih:cccccccccc3333333333cccccccccc3333333333&dn=Dune",
            }
        ]
        download_service = MagicMock()
        download_service.add_torrent.return_value = True
        download_service.get_completed_file_path.return_value = "/downloads/dune.epub"
        import_service = MagicMock()
        import_service.import_epub.return_value = True

        service = PipelineService(
            search_service=search_service,
            download_service=download_service,
            import_service=import_service,
            db_session_factory=_session_factory(db_session),
            ws_manager=ws_manager,
        )

        book = create_test_book(db_session, title="Dune", author_name="Frank Herbert")
        db_session.commit()
        book_id = cast(int, book.id)

        assert service.process_wanted_books() == 1
        book = _fresh_book(db_session, book_id)
        download_id = cast(int, book.downloads[0].id)

        assert service.process_grabbed_books() == 1
        assert service.process_downloading_books() == 1
        assert service.process_importing_books() == 1

        fresh_book = _fresh_book(db_session, book_id)
        assert _book_status(fresh_book) == BookStatus.IN_LIBRARY.value

        status_payloads = _event_payloads(ws_manager, "book_status_changed")
        assert [payload["new_status"] for payload in status_payloads] == [
            BookStatus.SEARCHING.value,
            BookStatus.GRABBED.value,
            BookStatus.DOWNLOADING.value,
            BookStatus.IMPORTING.value,
            BookStatus.IN_LIBRARY.value,
        ]
        assert status_payloads[0] == {
            "book_id": book_id,
            "old_status": BookStatus.WANTED.value,
            "new_status": BookStatus.SEARCHING.value,
            "title": "Dune",
        }

        assert _event_payloads(ws_manager, "book_searching") == [{"book_id": book_id, "title": "Dune", "attempt": 1}]
        assert _event_payloads(ws_manager, "book_grabbed") == [
            {
                "book_id": book_id,
                "title": "Dune",
                "release_title": "Dune Release.epub",
                "indexer": "IndexerOne",
            }
        ]
        assert _event_payloads(ws_manager, "download_started") == [
            {"book_id": book_id, "download_id": download_id, "title": "Dune"}
        ]
        assert _event_payloads(ws_manager, "download_completed") == [
            {
                "book_id": book_id,
                "download_id": download_id,
                "file_path": "/downloads/dune.epub",
            }
        ]
        assert _event_payloads(ws_manager, "import_completed") == [
            {
                "book_id": book_id,
                "title": "Dune",
                "file_path": "/downloads/dune.epub",
            }
        ]

    def test_fail_book_emits_book_failed_payload(self, db_session):
        ws_manager = MagicMock()
        service = PipelineService(db_session_factory=_session_factory(db_session), ws_manager=ws_manager)
        book = create_test_book(db_session, title="Broken Book", status=BookStatus.SEARCHING.value)
        db_session.commit()
        book_id = cast(int, book.id)

        service._fail_book(book, db_session, "Search provider down")

        failed_payloads = _event_payloads(ws_manager, "book_failed")
        assert failed_payloads == [{"book_id": book_id, "title": "Broken Book", "reason": "Search provider down"}]
        assert _book_status(_fresh_book(db_session, book_id)) == BookStatus.FAILED.value

    def test_fail_download_emits_download_failed_payload(self, db_session):
        ws_manager = MagicMock()
        service = PipelineService(db_session_factory=_session_factory(db_session), ws_manager=ws_manager)
        book = create_test_book(db_session, title="Queued Book", status=BookStatus.GRABBED.value)
        db_session.commit()
        download = _create_download(db_session, book, torrent_hash="hash-fail")
        book_id = cast(int, book.id)
        download_id = cast(int, download.id)

        service._fail_download(download, db_session, "add_torrent returned False")

        failed_payloads = _event_payloads(ws_manager, "download_failed")
        assert failed_payloads == [
            {
                "book_id": book_id,
                "download_id": download_id,
                "reason": "add_torrent returned False",
            }
        ]
        assert _download_status(_fresh_download(db_session, download_id)) == DownloadStatus.FAILED.value


class TestDownloadServiceEvents:
    def test_monitor_downloads_emits_progress_payload(self, db_session):
        ws_manager = MagicMock()
        qbit = MagicMock()
        service = DownloadService(qbit, _session_factory(db_session), ws_manager=ws_manager)
        book = create_test_book(db_session, title="Progress Book", status=BookStatus.DOWNLOADING.value)
        db_session.commit()
        download = _create_download(
            db_session,
            book,
            torrent_hash="progress-hash",
            status=DownloadStatus.DOWNLOADING.value,
        )
        download_id = cast(int, download.id)

        qbit.get_torrents.return_value = [
            {
                "hash": download.torrent_hash,
                "state": TorrentState.DOWNLOADING,
                "progress": 0.42,
                "dlspeed": 123456,
                "eta": 321,
            }
        ]

        assert service.monitor_downloads() == 1
        assert _event_payloads(ws_manager, "download_progress") == [
            {
                "download_id": download_id,
                "progress": 0.42,
                "download_speed": 123456,
                "eta": 321,
            }
        ]

    def test_monitor_downloads_emits_failed_payload_for_error_state(self, db_session):
        ws_manager = MagicMock()
        qbit = MagicMock()
        service = DownloadService(qbit, _session_factory(db_session), ws_manager=ws_manager)
        book = create_test_book(db_session, title="Error Book", status=BookStatus.DOWNLOADING.value)
        db_session.commit()
        download = _create_download(
            db_session,
            book,
            torrent_hash="error-hash",
            status=DownloadStatus.DOWNLOADING.value,
        )
        book_id = cast(int, book.id)
        download_id = cast(int, download.id)

        qbit.get_torrents.return_value = [{"hash": download.torrent_hash, "state": TorrentState.ERROR, "progress": 0.0}]

        assert service.monitor_downloads() == 1

        failed_payloads = _event_payloads(ws_manager, "download_failed")
        assert failed_payloads == [
            {
                "book_id": book_id,
                "download_id": download_id,
                "reason": f"Torrent in error state ({TorrentState.ERROR})",
            }
        ]
        assert _download_status(_fresh_download(db_session, download_id)) == DownloadStatus.FAILED.value


class TestImportServiceEvents:
    def test_import_book_emits_started_and_completed_events(self, db_session, tmp_path: Path):
        ws_manager = MagicMock()
        epub_service = MagicMock()
        epub_service.validate_epub.return_value = True

        source_epub = tmp_path / "source.epub"
        create_test_epub(str(source_epub), "Source Book", "Source Author")
        library_root = tmp_path / "library"
        library_root.mkdir()

        root_folder = _create_root_folder(db_session, library_root)
        book = create_test_book(
            db_session,
            title="Imported Book",
            author_name="Import Author",
            status=BookStatus.DOWNLOADING.value,
            root_folder_id=root_folder.id,
        )
        db_session.commit()
        book_id = cast(int, book.id)

        service = ImportService(db_session, epub_service=epub_service, ws_manager=ws_manager)
        imported_book = service.import_book(book_id, source_epub)

        assert _book_status(imported_book) == BookStatus.IN_LIBRARY.value

        status_payloads = _event_payloads(ws_manager, "book_status_changed")
        assert status_payloads == [
            {
                "book_id": book_id,
                "old_status": BookStatus.DOWNLOADING.value,
                "new_status": BookStatus.IMPORTING.value,
                "title": "Imported Book",
            },
            {
                "book_id": book_id,
                "old_status": BookStatus.IMPORTING.value,
                "new_status": BookStatus.IN_LIBRARY.value,
                "title": "Imported Book",
            },
        ]
        assert _event_payloads(ws_manager, "import_started") == [{"book_id": book_id, "title": "Imported Book"}]

        completed_payload = _event_payloads(ws_manager, "import_completed")
        assert completed_payload == [
            {
                "book_id": book_id,
                "title": "Imported Book",
                "file_path": str(library_root / "Imported Book.epub"),
            }
        ]

    def test_import_book_emits_import_failed_event(self, db_session, tmp_path: Path):
        ws_manager = MagicMock()
        epub_service = MagicMock()
        epub_service.validate_epub.return_value = True
        epub_service.write_metadata.side_effect = BookImportError("metadata write failed")

        source_epub = tmp_path / "source.epub"
        create_test_epub(str(source_epub), "Source Book", "Source Author")
        library_root = tmp_path / "library"
        library_root.mkdir()

        root_folder = _create_root_folder(db_session, library_root)
        book = create_test_book(
            db_session,
            title="Failing Import",
            author_name="Import Author",
            status=BookStatus.DOWNLOADING.value,
            root_folder_id=root_folder.id,
        )
        db_session.commit()
        book_id = cast(int, book.id)

        service = ImportService(db_session, epub_service=epub_service, ws_manager=ws_manager)

        with pytest.raises(BookImportError, match="metadata write failed"):
            service.import_book(book_id, source_epub)

        failed_payloads = _event_payloads(ws_manager, "import_failed")
        assert failed_payloads[0]["book_id"] == book_id
        assert failed_payloads[0]["title"] == "Failing Import"
        assert "metadata write failed" in failed_payloads[0]["reason"]
        assert _book_status(_fresh_book(db_session, book_id)) == BookStatus.FAILED.value
