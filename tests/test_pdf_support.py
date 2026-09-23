"""PDF support: PdfService, format helpers, PDF import, and the PDF→EPUB upgrade track."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pypdf import PdfReader, PdfWriter

from backend.models.book import (
    Author,
    Book,
    BookStatus,
    Download,
    DownloadStatus,
    EpubMetaState,
    EreaderDeliveryStatus,
    FolderOrganization,
    RootFolder,
)
from backend.services.book_formats import BookFormat, format_of, media_type_for, pick_book_file
from backend.services.download_service import DownloadService
from backend.services.import_service import ImportInvalidEpubError, ImportService, ImportStateError
from backend.services.pdf_service import PdfService
from backend.services.pipeline_service import PipelineService
from backend.services.rename_service import RenameService
from backend.services.search_service import ScoredResult
from backend.utils.clock import naive_utcnow
from tests.helpers import create_test_epub, create_test_pdf


@pytest.fixture(autouse=True)
def _title_only_template(monkeypatch):
    config = {"library": {"naming_template": "{Author} - {Title}"}}
    monkeypatch.setattr("backend.services.import_service.load_config", lambda: config)
    monkeypatch.setattr("backend.services.rename_service.load_config", lambda: config)


@pytest.fixture
def lib_root(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


def _make_book(db, lib_root: Path, *, status: str, file_path: str | None = None, title: str = "Wandersail") -> Book:
    rf = RootFolder(
        name="Books", path=str(lib_root), folder_organization=FolderOrganization.AUTHOR.value, created_at=naive_utcnow()
    )
    author = Author(name="Brandon Sanderson", created_at=naive_utcnow())
    db.add_all([rf, author])
    db.flush()
    book = Book(
        title=title,
        hardcover_id=f"hc-{title}",
        author_id=author.id,
        status=status,
        root_folder_id=rf.id,
        file_path=file_path,
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
    )
    db.add(book)
    db.commit()
    return book


def _pdf_book(db, lib_root: Path) -> tuple[Book, Path]:
    pdf = lib_root / "Brandon Sanderson" / "Brandon Sanderson - Wandersail.pdf"
    create_test_pdf(str(pdf), title="Wandersail", author="Brandon Sanderson")
    book = _make_book(
        db,
        lib_root,
        status=BookStatus.IN_LIBRARY.value,
        file_path="Brandon Sanderson/Brandon Sanderson - Wandersail.pdf",
    )
    return book, pdf


class TestPdfService:
    def test_validate_accepts_pdf_and_rejects_garbage(self, tmp_path):
        good = tmp_path / "good.pdf"
        bad = tmp_path / "bad.pdf"
        create_test_pdf(str(good))
        bad.write_bytes(b"not a pdf")

        assert PdfService().validate(good) is True
        assert PdfService().validate(bad) is False

    def test_encrypted_pdf_is_drm(self, tmp_path):
        path = tmp_path / "locked.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("secret")
        with open(path, "wb") as fh:
            writer.write(fh)

        assert PdfService().is_drm_protected(path) is True

    def test_empty_password_pdf_is_not_drm(self, tmp_path):
        # Old converters often encrypt with an empty user password and no restrictions.
        path = tmp_path / "open.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata({"/Title": "Old Scan"})
        writer.encrypt(user_password="", owner_password="owner", algorithm="RC4-40")
        with open(path, "wb") as fh:
            writer.write(fh)
        svc = PdfService()

        assert svc.is_drm_protected(path) is False
        assert svc.validate(path) is True
        assert svc.read_metadata(path).title == "Old Scan"

        from backend.services.epub_service import EpubMetadata

        svc.write_metadata(path, EpubMetadata(title="Real Title", authors=["Jane Doe"]))

        assert svc.read_metadata(path).title == "Real Title"
        assert PdfReader(path).is_encrypted is False

    def test_write_then_read_round_trip(self, tmp_path):
        from backend.services.epub_service import EpubMetadata

        path = tmp_path / "book.pdf"
        create_test_pdf(str(path), title="Junk Title")

        PdfService().write_metadata(path, EpubMetadata(title="Real Title", authors=["Jane Doe"]))

        meta = PdfService().read_metadata(path)
        assert meta.title == "Real Title"
        assert meta.authors == ["Jane Doe"]
        assert len(PdfReader(path).pages) == 1
        assert not list(tmp_path.glob("*.tmp"))

    def test_empty_metadata_is_not_low_confidence(self, tmp_path):
        path = tmp_path / "book.pdf"
        create_test_pdf(str(path))
        book = Book(title="Anything", author=Author(name="Someone"))

        assert PdfService().verify_content(path, book) == (True, None)

    def test_mismatched_metadata_is_low_confidence(self, tmp_path):
        path = tmp_path / "book.pdf"
        create_test_pdf(str(path), title="Completely Different", author="Other Person")
        book = Book(title="Wandersail", author=Author(name="Brandon Sanderson"))

        ok, reason = PdfService().verify_content(path, book)
        assert ok is False
        assert reason and reason.startswith("low_confidence")


class TestBookFormats:
    def test_format_of(self):
        assert format_of("a/b.EPUB") == BookFormat.EPUB
        assert format_of("a/b.pdf") == BookFormat.PDF
        assert format_of("a/b.mobi") is None
        assert format_of(None) is None

    def test_media_type_for(self):
        assert media_type_for("x.pdf") == "application/pdf"
        assert media_type_for("x.epub") == "application/epub+zip"

    def test_pick_prefers_epub(self):
        assert pick_book_file(["b/book.pdf", "b/book.epub", "b/cover.jpg"]) == "b/book.epub"

    def test_pick_single_pdf(self):
        assert pick_book_file(["b/book.pdf", "b/cover.jpg"]) == "b/book.pdf"

    def test_pick_refuses_pdf_when_not_allowed(self):
        assert pick_book_file(["b/book.pdf"], allow_pdf=False) is None

    def test_pick_matches_title_in_pdf_pack(self):
        names = ["pack/Verso.Polemics.Alain Badiou.pdf", "pack/Wandersail.pdf", "pack/Mapping Ideology.pdf"]
        assert pick_book_file(names, title="Wandersail") == "pack/Wandersail.pdf"

    def test_pick_rejects_unrelated_pdf_pack(self):
        names = ["pack/Polemics.pdf", "pack/Mapping Ideology.pdf"]
        assert pick_book_file(names, title="Wandersail") is None


class TestPdfImport:
    def test_import_keeps_pdf_suffix_and_writes_metadata(self, db_session, lib_root, tmp_path):
        source = tmp_path / "download" / "whatever.pdf"
        create_test_pdf(str(source), title="scan_0001")
        book = _make_book(db_session, lib_root, status=BookStatus.DOWNLOADING.value)

        result = ImportService(db_session).import_book(book.id, source)

        assert result.status == BookStatus.IN_LIBRARY.value
        assert result.file_path == "Brandon Sanderson/Brandon Sanderson - Wandersail.pdf"
        assert result.epub_meta_state == EpubMetaState.SYNCED.value
        meta = PdfService().read_metadata(lib_root / result.file_path)
        assert meta.title == "Wandersail"
        assert meta.authors == ["Brandon Sanderson"]
        assert result.to_dict()["format"] == "pdf"

    def test_rename_keeps_pdf_suffix(self, db_session, lib_root):
        pdf = lib_root / "old name.pdf"
        create_test_pdf(str(pdf))
        book = _make_book(db_session, lib_root, status=BookStatus.IN_LIBRARY.value, file_path="old name.pdf")

        [item] = RenameService(db_session).preview()

        assert item.book_id == book.id
        assert item.new_path == "Brandon Sanderson/Brandon Sanderson - Wandersail.pdf"


class TestReplaceWithEpub:
    def test_swaps_pdf_for_epub_and_rearms_delivery(self, db_session, lib_root, tmp_path, monkeypatch):
        book, pdf = _pdf_book(db_session, lib_root)
        book.hardcover_status = "want_to_read"
        book.ereader_delivery_status = EreaderDeliveryStatus.DELIVERED.value
        db_session.commit()
        monkeypatch.setattr(
            "backend.services.import_service.load_config",
            lambda: {
                "library": {"naming_template": "{Author} - {Title}"},
                "ereaders": [{"id": "k", "hostname": "kindle"}],
                "transfer": {"sync_shelves": {"want_to_read": True}},
            },
        )
        epub = tmp_path / "dl" / "Wandersail.epub"
        create_test_epub(str(epub), "Wandersail", "Brandon Sanderson")

        ImportService(db_session).replace_with_epub(book.id, epub)

        db_session.refresh(book)
        assert book.status == BookStatus.IN_LIBRARY.value
        assert book.file_path == "Brandon Sanderson/Brandon Sanderson - Wandersail.epub"
        assert book.format == BookFormat.EPUB
        assert (lib_root / book.file_path).exists()
        assert not pdf.exists()
        assert book.ereader_delivery_status == EreaderDeliveryStatus.PENDING.value

    def test_invalid_epub_leaves_pdf_in_place(self, db_session, lib_root, tmp_path):
        book, pdf = _pdf_book(db_session, lib_root)
        bogus = tmp_path / "bogus.epub"
        bogus.write_bytes(b"nope")

        with pytest.raises(ImportInvalidEpubError):
            ImportService(db_session).replace_with_epub(book.id, bogus)

        db_session.refresh(book)
        assert book.file_path.endswith(".pdf")
        assert pdf.exists()

    def test_refuses_epub_backed_book(self, db_session, lib_root, tmp_path):
        book = _make_book(db_session, lib_root, status=BookStatus.IN_LIBRARY.value, file_path="x.epub")
        epub = tmp_path / "new.epub"
        create_test_epub(str(epub), "Wandersail", "Brandon Sanderson")

        with pytest.raises(ImportStateError):
            ImportService(db_session).replace_with_epub(book.id, epub)


def _scored(fmt: str = "epub") -> ScoredResult:
    return ScoredResult(
        guid="g",
        indexer_id=1,
        indexer="MAM",
        title=f"Wandersail [{fmt.upper()}]",
        size=2_000_000,
        seeders=5,
        leechers=0,
        download_url=None,
        magnet_url="magnet:?xt=urn:btih:" + "a" * 40,
        publish_date=None,
        protocol="torrent",
        format=fmt,
    )


def _pipeline(db_session, **services) -> PipelineService:
    return PipelineService(db_session_factory=lambda: db_session, **services)


class TestUpgradePipeline:
    def test_search_upgrade_grabs_epub_without_touching_book_status(self, db_session, lib_root):
        book, _ = _pdf_book(db_session, lib_root)
        search = MagicMock()
        search.search_book.return_value = [_scored("epub")]

        grabbed = _pipeline(db_session, search_service=search).search_single_book(book.id)

        assert grabbed == 1
        search.search_book.assert_called_once_with("Wandersail", "Brandon Sanderson", allow_pdf=False)
        db_session.expire_all()
        [download] = db_session.query(Download).all()
        assert download.is_upgrade is True
        assert download.status == DownloadStatus.QUEUED.value
        assert db_session.get(Book, book.id).status == BookStatus.IN_LIBRARY.value

    def test_upgrade_search_ignores_pdf_results(self, db_session, lib_root):
        book, _ = _pdf_book(db_session, lib_root)
        search = MagicMock()
        search.search_book.return_value = [_scored("pdf")]

        assert _pipeline(db_session, search_service=search).search_upgrades() == 0
        assert db_session.query(Download).count() == 0

    def test_process_upgrades_end_to_end(self, db_session, lib_root, tmp_path):
        book, pdf = _pdf_book(db_session, lib_root)
        download = Download(
            book_id=book.id,
            torrent_hash="a" * 40,
            torrent_name="Wandersail EPUB",
            indexer_name="MAM",
            download_url="magnet:?xt=urn:btih:" + "a" * 40,
            size=1,
            seeders=1,
            status=DownloadStatus.QUEUED.value,
            is_upgrade=True,
        )
        db_session.add(download)
        db_session.commit()
        epub = tmp_path / "dl" / "Wandersail.epub"
        create_test_epub(str(epub), "Wandersail", "Brandon Sanderson")

        downloads = MagicMock()
        downloads.add_torrent.return_value = True
        downloads.get_completed_file_path.return_value = str(epub)
        pipeline = _pipeline(db_session, download_service=downloads, import_service=ImportService(db_session))
        book_id, download_id = book.id, download.id

        assert pipeline.process_upgrades() == 0  # QUEUED → DOWNLOADING
        assert pipeline.process_upgrades() == 1  # DOWNLOADING → COMPLETED → swapped in

        assert db_session.get(Download, download_id).status == DownloadStatus.IMPORTED.value
        upgraded = db_session.get(Book, book_id)
        assert upgraded.status == BookStatus.IN_LIBRARY.value
        assert upgraded.file_path.endswith(".epub")
        assert not pdf.exists()

    def test_completed_upgrade_without_epub_fails_download(self, db_session, lib_root):
        book, pdf = _pdf_book(db_session, lib_root)
        download = Download(
            book_id=book.id,
            torrent_hash="b" * 40,
            torrent_name="Wandersail",
            indexer_name="MAM",
            download_url="x",
            size=1,
            seeders=1,
            status=DownloadStatus.DOWNLOADING.value,
            is_upgrade=True,
        )
        db_session.add(download)
        db_session.commit()
        downloads = MagicMock()
        downloads.get_completed_file_path.return_value = None
        downloads.is_torrent_complete.return_value = True
        book_id, download_id = book.id, download.id

        _pipeline(db_session, download_service=downloads, import_service=MagicMock()).process_upgrades()

        assert db_session.get(Download, download_id).status == DownloadStatus.FAILED.value
        assert db_session.get(Book, book_id).status == BookStatus.IN_LIBRARY.value
        assert pdf.exists()


class TestUpgradeCompletionInDownloadService:
    def test_handle_completed_leaves_upgrade_book_in_library(self, db_session, lib_root):
        book, _ = _pdf_book(db_session, lib_root)
        download = Download(
            book_id=book.id,
            torrent_hash="c" * 40,
            torrent_name="Wandersail EPUB",
            indexer_name="MAM",
            download_url="x",
            size=1,
            seeders=1,
            status=DownloadStatus.DOWNLOADING.value,
            is_upgrade=True,
        )
        db_session.add(download)
        db_session.commit()
        qbit = MagicMock()
        qbit.get_completed_file_path.return_value = Path("/dl/Wandersail.epub")

        ok = DownloadService(qbit, lambda: db_session).handle_completed(download, db=db_session)

        assert ok is True
        qbit.get_completed_file_path.assert_called_once_with("c" * 40, title="Wandersail", allow_pdf=False)
        db_session.expire_all()
        assert db_session.get(Download, download.id).status == DownloadStatus.COMPLETED.value
        assert db_session.get(Book, book.id).status == BookStatus.IN_LIBRARY.value
