# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false

"""Acceptance tests for RssSyncService — covers all 15 scenarios (AS1-AS15)."""

import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import MagicMock, patch

import pytest
import requests
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.book import Author, Book, BookStatus, Download
from backend.models.rss import RssIndexerState, RssSeenItem
from backend.services.pipeline_service import PipelineService
from backend.services.rss_sync_service import RssSyncService
from backend.services.search_service import SearchService
from tests.helpers import create_test_book


@pytest.fixture
def db_session():
    """In-memory SQLite session shared across service calls.

    Service code calls ``db.close()`` in finally blocks; SQLAlchemy treats this
    as a soft close that ends the current transaction but keeps the session
    usable for subsequent queries — same pattern as test_pipeline_service.py.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def fake_ws():
    """Fake WebSocketManager that records ``broadcast_sync`` calls."""
    fake = MagicMock()
    fake.events = []

    def record(event, data):
        fake.events.append((event, dict(data)))

    fake.broadcast_sync = MagicMock(side_effect=record)
    return fake


@pytest.fixture(autouse=True)
def mock_load_config():
    """Patch ``load_config`` inside RssSyncService so tests don't read config.yaml.

    Tests that need rss.enabled=False can override via the returned MagicMock.
    """
    config = {
        "rss": {
            "enabled": True,
            "max_age_days": 3,
            "limit": 100,
            "caps_cache_seconds": 3600,
            "cleanup_retention_days": 60,
        }
    }
    with patch("backend.services.rss_sync_service.load_config", return_value=config) as mock:
        yield mock


_HASH_COUNTER = {"n": 0}


def _next_hash() -> str:
    """Generate a unique 40-char hex BitTorrent info hash."""
    _HASH_COUNTER["n"] += 1
    return f"{_HASH_COUNTER['n']:040x}"


def make_rss_item(
    *,
    guid,
    title,
    author="J.R.R. Tolkien",
    indexer_id=1,
    indexer="TestIndexer",
    seeders=42,
    size=5_000_000,
    publish_date="2025-04-29T12:00:00+00:00",
    categories=None,
    magnet_url=None,
    download_url=None,
):
    """Build a normalized RSS item dict.

    Mirrors ``ProwlarrClient._normalize_result`` shape but adds an ``author`` key
    so ``SearchService._evaluate`` can perform surname matching.
    """
    info_hash = _next_hash()
    return {
        "guid": guid,
        "indexer_id": indexer_id,
        "indexer": indexer,
        "title": title,
        "author": author,
        "size": size,
        "seeders": seeders,
        "leechers": 5,
        "download_url": download_url or f"https://example.com/download/{guid}",
        "magnet_url": magnet_url or f"magnet:?xt=urn:btih:{info_hash}&dn={guid}",
        "categories": categories or [{"id": 7020}],
        "protocol": "torrent",
        "publish_date": publish_date,
    }


def make_meta_ok():
    return {"status": "ok", "retry_after_seconds": None, "error": None, "http_status": 200}


def make_meta_error(http_status=500, error="HTTP 500"):
    return {
        "status": "error",
        "retry_after_seconds": None,
        "error": error,
        "http_status": http_status,
    }


def seed_indexer_state(db, indexer_id=1, indexer_name="TestIndexer", *, post_bootstrap=True):
    """Insert an RssIndexerState row that skips bootstrap and caps fetch.

    With ``post_bootstrap=True`` (default), ``last_poll_at`` is set so the next
    sync proceeds to match-and-grab. Caps are pre-cached as supporting book search.
    """
    now = datetime.utcnow()
    state = RssIndexerState(
        indexer_id=indexer_id,
        indexer_name=indexer_name,
        last_poll_at=(now - timedelta(minutes=10)) if post_bootstrap else None,
        last_status="ok" if post_bootstrap else None,
        last_error=None,
        items_seen_count=0,
        items_grabbed_count=0,
        retry_not_before_at=None,
        caps_cached_at=now - timedelta(minutes=10),
        caps_supports_book_search=True,
    )
    db.add(state)
    db.commit()
    return state


def build_service(db_session, fake_ws, *, prowlarr=None, qbit_add_torrent=True):
    """Wire up RssSyncService with real SearchService, real PipelineService, mocked clients."""

    def factory():
        return db_session

    if prowlarr is None:
        prowlarr = MagicMock()

    search_service = SearchService(prowlarr_client=prowlarr, db=db_session)

    download_service = MagicMock()
    download_service.add_torrent.return_value = qbit_add_torrent

    pipeline_service = PipelineService(
        search_service=search_service,
        download_service=download_service,
        db_session_factory=factory,
        ws_manager=fake_ws,
    )

    rss_service = RssSyncService(
        prowlarr_client=prowlarr,
        search_service=search_service,
        pipeline_service=pipeline_service,
        ws_manager=fake_ws,
        db_session_factory=factory,
    )
    return rss_service, prowlarr


def test_first_poll_no_grab(db_session, fake_ws):
    """AS1: First poll for a fresh indexer marks all items seen, ZERO grabs."""
    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    create_test_book(db_session, title="Foundation", author_name="Isaac Asimov")
    db_session.commit()

    items = [
        make_rss_item(guid="hobbit-1", title="The Hobbit (EPUB)", author="J.R.R. Tolkien"),
        make_rss_item(guid="foundation-1", title="Foundation (EPUB)", author="Isaac Asimov"),
        make_rss_item(guid="other-1", title="Some Other Book (EPUB)", author="Anonymous"),
    ]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.get_indexer_caps.return_value = {"book_search_supported": True, "categories": [7020]}
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    assert summary["status"] == "ok"
    assert summary["items_grabbed"] == 0
    assert summary["items_found"] == 0
    assert summary["indexers_polled"] == 1

    seen = db_session.query(RssSeenItem).filter(RssSeenItem.indexer_id == 1).all()
    assert len(seen) == 3
    assert {row.guid for row in seen} == {"hobbit-1", "foundation-1", "other-1"}

    assert db_session.query(Download).count() == 0

    polled_events = [data for ev, data in fake_ws.events if ev == "rss_indexer_polled"]
    assert len(polled_events) == 1
    assert polled_events[0]["bootstrap"] is True
    assert polled_events[0]["items_seen"] == 3


def test_indexer_error_isolation(db_session, fake_ws):
    """AS2: One indexer 500s, the other succeeds — second indexer still grabs."""
    seed_indexer_state(db_session, indexer_id=1, indexer_name="BadIndexer")
    seed_indexer_state(db_session, indexer_id=2, indexer_name="GoodIndexer")

    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    db_session.commit()

    good_items = [
        make_rss_item(
            guid="hobbit-from-good",
            title="The Hobbit (EPUB)",
            author="J.R.R. Tolkien",
            indexer_id=2,
            indexer="GoodIndexer",
        )
    ]

    def fetch_rss_dispatcher(indexer_id, name, **kwargs):
        if indexer_id == 1:
            return [], make_meta_error(http_status=500)
        return good_items, make_meta_ok()

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [
        {"id": 1, "name": "BadIndexer", "enable": True},
        {"id": 2, "name": "GoodIndexer", "enable": True},
    ]
    prowlarr.get_indexer_caps.return_value = {"book_search_supported": True, "categories": [7020]}
    prowlarr.fetch_rss.side_effect = fetch_rss_dispatcher

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    bad_state = db_session.get(RssIndexerState, 1)
    good_state = db_session.get(RssIndexerState, 2)
    db_session.refresh(bad_state)
    db_session.refresh(good_state)

    assert bad_state.last_status == "error"
    assert good_state.last_status == "ok"

    assert summary["items_grabbed"] == 1
    assert db_session.query(Download).count() == 1


def test_caps_cached_one_hour(db_session, fake_ws):
    """AS3: Caps fetched once, cached for >=1h, second cycle reuses cache."""
    items = [make_rss_item(guid="x-1", title="Anything (EPUB)")]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.get_indexer_caps.return_value = {"book_search_supported": True, "categories": [7020]}
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)

    rss_service.run_sync_cycle()
    rss_service.run_sync_cycle()

    assert prowlarr.get_indexer_caps.call_count == 1


def test_guid_dedup(db_session, fake_ws):
    """AS4: Same GUID across 2 polls -> 1 row in rss_seen_item, 1 grab attempt."""
    seed_indexer_state(db_session)
    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    db_session.commit()

    items = [
        make_rss_item(guid="hobbit-dedup", title="The Hobbit (EPUB)", author="J.R.R. Tolkien"),
    ]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)

    summary1 = rss_service.run_sync_cycle()
    summary2 = rss_service.run_sync_cycle()

    seen_rows = db_session.query(RssSeenItem).filter(RssSeenItem.guid == "hobbit-dedup").all()
    assert len(seen_rows) == 1

    assert summary1["items_grabbed"] == 1
    assert summary2["items_grabbed"] == 0

    assert db_session.query(Download).count() == 1


def test_audiobook_rejected(db_session, fake_ws):
    """AS5: RSS item with audiobook tag is rejected — no grab."""
    seed_indexer_state(db_session)
    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    db_session.commit()

    items = [
        make_rss_item(
            guid="hobbit-audiobook",
            title="The Hobbit [M4B] [audiobook] by J.R.R. Tolkien",
            author="J.R.R. Tolkien",
        )
    ]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    assert summary["items_grabbed"] == 0
    assert db_session.query(Download).count() == 0

    seen = db_session.query(RssSeenItem).filter(RssSeenItem.guid == "hobbit-audiobook").all()
    assert len(seen) == 1


def test_fuzzy_title_match(db_session, fake_ws):
    """AS6: RSS item with typo'd title still matches wanted book via fuzzy similarity."""
    seed_indexer_state(db_session)
    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    db_session.commit()

    items = [
        make_rss_item(
            guid="hobbit-typo",
            title="The Hobit (EPUB)",
            author="J.R.R. Tolkien",
        )
    ]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    assert summary["items_grabbed"] == 1, "Fuzzy match should grab despite title typo"
    assert db_session.query(Download).count() == 1


def test_websocket_events(db_session, fake_ws):
    """AS7: WS events fire in the documented order with correct payload schema."""
    seed_indexer_state(db_session)
    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    db_session.commit()

    items = [make_rss_item(guid="hobbit-ws", title="The Hobbit (EPUB)", author="J.R.R. Tolkien")]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    rss_service.run_sync_cycle()

    event_names = [ev for ev, _ in fake_ws.events]
    rss_events = [ev for ev in event_names if ev.startswith("rss_")]

    assert rss_events[0] == "rss_sync_started"
    assert rss_events[-1] == "rss_sync_completed"

    assert "rss_match_found" in rss_events
    assert "rss_grabbed" in rss_events
    assert rss_events.index("rss_match_found") < rss_events.index("rss_grabbed")

    assert "rss_indexer_polled" in rss_events

    match_data = next(d for ev, d in fake_ws.events if ev == "rss_match_found")
    assert match_data["indexer"] == "TestIndexer"
    assert match_data["guid"] == "hobbit-ws"
    assert match_data["title"] == "The Hobbit (EPUB)"
    assert "similarity" in match_data
    assert "book_id" in match_data


def test_concurrent_manual_trigger_returns_409(db_session, fake_ws):
    """AS8: Service-level — second sync invocation while first holds lock returns in_progress."""
    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = []
    prowlarr.get_indexer_caps.return_value = {"book_search_supported": False, "categories": []}
    prowlarr.fetch_rss.return_value = ([], make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)

    assert rss_service._sync_lock.acquire(blocking=False) is True
    try:
        result = rss_service.run_sync_cycle(trigger="manual")
        assert result == {"status": "in_progress"}
        assert rss_service.is_sync_in_progress() is True
    finally:
        rss_service._sync_lock.release()

    assert rss_service.is_sync_in_progress() is False
    summary = rss_service.run_sync_cycle(trigger="manual")
    assert summary["status"] == "ok"


def test_disabled_no_op(db_session, fake_ws, mock_load_config):
    """AS9: rss.enabled=False -> run_sync_cycle returns disabled, no Prowlarr calls."""
    mock_load_config.return_value = {"rss": {"enabled": False}}

    prowlarr = MagicMock()
    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)

    result = rss_service.run_sync_cycle(trigger="scheduled")

    assert result == {
        "status": "disabled",
        "trigger": "scheduled",
        "indexers_polled": 0,
        "items_found": 0,
        "items_grabbed": 0,
        "duration_ms": 0,
    }
    prowlarr.get_indexers.assert_not_called()
    prowlarr.get_indexer_caps.assert_not_called()
    prowlarr.fetch_rss.assert_not_called()


def test_invalid_cron_graceful(db_session, fake_ws, mock_load_config):
    """AS10: Cron validation lives at scheduler/main.py level — service ignores cron value.

    Pins the contract that ``RssSyncService`` never reads ``rss.cron_expression``;
    a malformed cron in config must not affect ``run_sync_cycle`` behavior.
    """
    mock_load_config.return_value = {
        "rss": {"enabled": True, "cron_expression": "invalid***!@#"},
    }

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = []
    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)

    summary = rss_service.run_sync_cycle()
    assert summary["status"] == "ok"
    assert summary["indexers_polled"] == 0


def test_no_book_search_capability_skipped(db_session, fake_ws):
    """AS11: Indexer with caps.book_search_supported=False -> skipped, no fetch."""
    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "NoBookIndexer", "enable": True}]
    prowlarr.get_indexer_caps.return_value = {"book_search_supported": False, "categories": []}

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    prowlarr.fetch_rss.assert_not_called()
    assert summary["status"] == "ok"

    polled = [d for ev, d in fake_ws.events if ev == "rss_indexer_polled"]
    assert len(polled) == 1
    assert polled[0]["status"] == "no_book_search"


def test_caps_timeout_skipped(db_session, fake_ws):
    """AS12: get_indexer_caps raising Timeout -> indexer marked error, others continue."""
    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    db_session.commit()

    items = [
        make_rss_item(
            guid="hobbit-good",
            title="The Hobbit (EPUB)",
            author="J.R.R. Tolkien",
            indexer_id=2,
            indexer="GoodIndexer",
        )
    ]
    seed_indexer_state(db_session, indexer_id=2, indexer_name="GoodIndexer")

    def caps_dispatcher(indexer_id):
        if indexer_id == 1:
            raise requests.Timeout("caps timed out")
        return {"book_search_supported": True, "categories": [7020]}

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [
        {"id": 1, "name": "TimeoutIndexer", "enable": True},
        {"id": 2, "name": "GoodIndexer", "enable": True},
    ]
    prowlarr.get_indexer_caps.side_effect = caps_dispatcher
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    db_session.expire_all()
    bad_state = db_session.get(RssIndexerState, 1)
    assert bad_state is not None
    assert bad_state.last_status == "error"
    assert "caps timed out" in (bad_state.last_error or "")

    assert summary["items_grabbed"] == 1
    assert db_session.query(Download).count() == 1


def test_missing_pubdate_skipped(db_session, fake_ws):
    """AS13: Service-level passthrough — items the parser dropped never reach the service.

    Items missing pubDate are silently dropped by ``parse_rss_xml`` upstream.
    The service trusts the items list it receives.
    """
    seed_indexer_state(db_session)
    create_test_book(db_session, title="The Hobbit", author_name="J.R.R. Tolkien")
    db_session.commit()

    items = [
        make_rss_item(guid="valid-1", title="The Hobbit (EPUB)", author="J.R.R. Tolkien"),
    ]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    seen = db_session.query(RssSeenItem).filter(RssSeenItem.indexer_id == 1).all()
    assert len(seen) == 1
    assert seen[0].guid == "valid-1"
    assert summary["items_grabbed"] == 1


def test_multiple_matches_deterministic(db_session, fake_ws):
    """AS14: Same RSS item matches 2 wanted books -> exactly ONE grab is created.

    Per-iteration grab attempts are dedup'd by ``Download.torrent_hash`` UNIQUE
    constraint. The first iterated book wins; the second hits IntegrityError and
    its grab returns 0. ``items_grabbed`` reflects exactly one increment.
    """
    seed_indexer_state(db_session)
    shared_author = Author(name="J.R.R. Tolkien")
    db_session.add(shared_author)
    db_session.flush()
    book_a = Book(
        title="The Hobbit",
        hardcover_id="test-hobbit",
        author_id=shared_author.id,
        status=BookStatus.WANTED.value,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    book_b = Book(
        title="The Hobbit Companion",
        hardcover_id="test-hobbit-companion",
        author_id=shared_author.id,
        status=BookStatus.WANTED.value,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add_all([book_a, book_b])
    db_session.commit()
    book_a_id, book_b_id = book_a.id, book_b.id

    items = [
        make_rss_item(
            guid="hobbit-shared",
            title="The Hobbit (EPUB)",
            author="J.R.R. Tolkien",
        )
    ]

    prowlarr = MagicMock()
    prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
    prowlarr.fetch_rss.return_value = (items, make_meta_ok())

    rss_service, _ = build_service(db_session, fake_ws, prowlarr=prowlarr)
    summary = rss_service.run_sync_cycle()

    downloads = db_session.query(Download).all()
    assert len(downloads) == 1
    assert summary["items_grabbed"] == 1

    assert downloads[0].book_id == book_a_id

    db_session.expire_all()
    book_b_fresh = db_session.get(Book, book_b_id)
    assert book_b_fresh.status == BookStatus.WANTED.value


def test_status_filter_atomic(fake_ws):
    """AS15: Book transitions to IN_LIBRARY mid-sync -> atomic CAS rejects the grab.

    Uses file-backed SQLite + ``threading.Barrier`` to interleave a status mutation
    between books-load and grab attempt. The atomic transition's
    ``UPDATE ... WHERE status = expected`` returns rowcount=0 because the DB
    status no longer matches the in-memory cached status.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "as15.db")
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        setup_session = Session()
        try:
            book = create_test_book(setup_session, title="The Hobbit", author_name="J.R.R. Tolkien")
            book_id = book.id

            now = datetime.utcnow()
            state = RssIndexerState(
                indexer_id=1,
                indexer_name="TestIndexer",
                last_poll_at=now - timedelta(minutes=10),
                last_status="ok",
                items_seen_count=0,
                items_grabbed_count=0,
                caps_cached_at=now - timedelta(minutes=10),
                caps_supports_book_search=True,
            )
            setup_session.add(state)
            setup_session.commit()
        finally:
            setup_session.close()

        barrier_pre_grab = Barrier(2)
        barrier_post_mutate = Barrier(2)

        items = [make_rss_item(guid="hobbit-as15", title="The Hobbit (EPUB)", author="J.R.R. Tolkien")]

        prowlarr = MagicMock()
        prowlarr.get_indexers.return_value = [{"id": 1, "name": "TestIndexer", "enable": True}]
        prowlarr.fetch_rss.return_value = (items, make_meta_ok())

        def factory():
            return Session()

        real_search = SearchService(prowlarr_client=prowlarr)
        original_evaluate = real_search.evaluate_and_rank

        def hooked_evaluate(*args, **kwargs):
            barrier_pre_grab.wait(timeout=5)
            barrier_post_mutate.wait(timeout=5)
            return original_evaluate(*args, **kwargs)

        real_search.evaluate_and_rank = hooked_evaluate

        download_service = MagicMock()
        download_service.add_torrent.return_value = True

        pipeline_service = PipelineService(
            search_service=real_search,
            download_service=download_service,
            db_session_factory=factory,
            ws_manager=fake_ws,
        )

        rss_service = RssSyncService(
            prowlarr_client=prowlarr,
            search_service=real_search,
            pipeline_service=pipeline_service,
            ws_manager=fake_ws,
            db_session_factory=factory,
        )

        def mutator():
            barrier_pre_grab.wait(timeout=5)
            mutator_session = Session()
            try:
                mutator_session.execute(
                    update(Book).where(Book.id == book_id).values(status=BookStatus.IN_LIBRARY.value)
                )
                mutator_session.commit()
            finally:
                mutator_session.close()
            barrier_post_mutate.wait(timeout=5)

        result_holder = {}

        def sync_runner():
            with patch("backend.services.rss_sync_service.load_config") as mc:
                mc.return_value = {"rss": {"enabled": True}}
                result_holder["summary"] = rss_service.run_sync_cycle()

        t_sync = threading.Thread(target=sync_runner)
        t_mutator = threading.Thread(target=mutator)
        t_sync.start()
        t_mutator.start()
        t_sync.join(timeout=15)
        t_mutator.join(timeout=15)

        assert not t_sync.is_alive(), "Sync thread hung"
        assert not t_mutator.is_alive(), "Mutator thread hung"

        summary = result_holder["summary"]
        assert summary["items_grabbed"] == 0, "Atomic transition must reject the grab"

        verify_session = Session()
        try:
            assert verify_session.query(Download).count() == 0
            book_after = verify_session.get(Book, book_id)
            assert book_after.status == BookStatus.IN_LIBRARY.value
        finally:
            verify_session.close()
        engine.dispose()
