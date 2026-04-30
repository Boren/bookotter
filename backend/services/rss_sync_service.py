import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, sessionmaker

from backend.clients.prowlarr_client import ProwlarrClient
from backend.config import load_config
from backend.constants import (
    EPUB_TITLE_SIMILARITY_THRESHOLD,
    RSS_CAPS_CACHE_SECONDS,
    RSS_CLEANUP_RETENTION_DAYS,
    RSS_DEFAULT_LIMIT,
    RSS_DEFAULT_MAX_AGE_DAYS,
)
from backend.models.book import Book, BookStatus
from backend.models.rss import RssIndexerState, RssSeenItem
from backend.services.pipeline_service import PipelineService
from backend.services.search_service import SearchService
from backend.services.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)


class RssSyncService:
    def __init__(
        self,
        prowlarr_client: ProwlarrClient,
        search_service: SearchService,
        pipeline_service: PipelineService,
        ws_manager: WebSocketManager | None,
        db_session_factory: sessionmaker[Session] | Callable[[], Session],
    ) -> None:
        self.prowlarr_client = prowlarr_client
        self.search_service = search_service
        self.pipeline_service = pipeline_service
        self.ws_manager = ws_manager
        self._session_factory = db_session_factory
        self._sync_lock = threading.Lock()
        self._last_sync_started_at: str | None = None
        self._last_sync_completed_at: str | None = None
        self._recent_matches: list[dict[str, Any]] = []

    def is_sync_in_progress(self) -> bool:
        return self._sync_lock.locked()

    def run_sync_cycle(self, trigger: str = "scheduled") -> dict:
        rss_config = load_config().get("rss", {})
        if rss_config.get("enabled") is False:
            return {"status": "disabled", "trigger": trigger, "indexers_polled": 0, "items_found": 0, "items_grabbed": 0, "duration_ms": 0}

        if not self._sync_lock.acquire(blocking=False):
            return {"status": "in_progress"}

        started_at = datetime.now(UTC).isoformat()
        self._last_sync_started_at = started_at
        started_monotonic = time.monotonic()
        summary = {
            "status": "ok",
            "trigger": trigger,
            "indexers_polled": 0,
            "items_found": 0,
            "items_grabbed": 0,
            "duration_ms": 0,
        }

        try:
            self._broadcast("rss_sync_started", {"trigger": trigger, "started_at": started_at})

            indexers = self.prowlarr_client.get_indexers()
            max_age_days = int(rss_config.get("max_age_days", RSS_DEFAULT_MAX_AGE_DAYS) or RSS_DEFAULT_MAX_AGE_DAYS)
            limit = int(rss_config.get("limit", RSS_DEFAULT_LIMIT) or RSS_DEFAULT_LIMIT)
            caps_cache_seconds = int(
                rss_config.get("caps_cache_seconds", RSS_CAPS_CACHE_SECONDS) or RSS_CAPS_CACHE_SECONDS
            )

            for indexer in indexers:
                if not indexer.get("enable", True):
                    continue
                try:
                    result = self._process_indexer(
                        indexer=indexer,
                        now=self._utcnow(),
                        max_age_days=max_age_days,
                        limit=limit,
                        caps_cache_seconds=caps_cache_seconds,
                    )
                    summary["indexers_polled"] += 1
                    summary["items_found"] += result["items_found"]
                    summary["items_grabbed"] += result["items_grabbed"]
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Unexpected RSS sync error for indexer %s: %s", indexer.get("name"), exc)
                    self._mark_indexer_error(
                        indexer_id=int(indexer.get("id") or 0),
                        indexer_name=str(indexer.get("name") or "unknown"),
                        error=str(exc),
                    )

            summary["duration_ms"] = int((time.monotonic() - started_monotonic) * 1000)
            completed_at = datetime.now(UTC).isoformat()
            self._last_sync_completed_at = completed_at
            self._broadcast(
                "rss_sync_completed",
                {
                    "completed_at": completed_at,
                    "indexers_polled": summary["indexers_polled"],
                    "items_found": summary["items_found"],
                    "items_grabbed": summary["items_grabbed"],
                    "duration_ms": summary["duration_ms"],
                },
            )
            return summary
        except Exception as exc:  # noqa: BLE001
            self._broadcast("rss_sync_failed", {"error": str(exc)})
            raise
        finally:
            self._sync_lock.release()

    def cleanup_old_seen_items(self) -> int:
        rss_config = load_config().get("rss", {})
        retention_days = int(
            rss_config.get("cleanup_retention_days", RSS_CLEANUP_RETENTION_DAYS) or RSS_CLEANUP_RETENTION_DAYS
        )
        cutoff = self._utcnow() - timedelta(days=retention_days)

        db = self._session_factory()
        try:
            deleted = db.query(RssSeenItem).filter(RssSeenItem.seen_at < cutoff).delete(synchronize_session=False)
            db.commit()
            return int(deleted or 0)
        finally:
            db.close()

    def _process_indexer(
        self,
        *,
        indexer: dict,
        now: datetime,
        max_age_days: int,
        limit: int,
        caps_cache_seconds: int,
    ) -> dict[str, int]:
        indexer_id = int(indexer["id"])
        indexer_name = str(indexer.get("name") or indexer_id)
        state = self._load_or_create_state(indexer_id=indexer_id, indexer_name=indexer_name)
        state_row = cast(Any, state)

        if self._is_retry_in_future(cast(datetime | None, state_row.retry_not_before_at), now):
            self._broadcast_indexer(indexer_id, indexer_name, "rate_limited", bootstrap=False, items_seen=0)
            return {"items_found": 0, "items_grabbed": 0}

        caps_stale = state_row.caps_cached_at is None or not self._is_caps_cache_fresh(
            cast(datetime, state_row.caps_cached_at), now, caps_cache_seconds
        )
        if caps_stale:
            caps = self.prowlarr_client.get_indexer_caps(indexer_id)
            state = self._update_caps(
                indexer_id=indexer_id,
                indexer_name=indexer_name,
                supports_book_search=bool(caps.get("book_search_supported")),
                cached_at=now,
            )
            state_row = cast(Any, state)

        if state_row.caps_supports_book_search is False:
            self._broadcast_indexer(indexer_id, indexer_name, "no_book_search", bootstrap=False, items_seen=0)
            return {"items_found": 0, "items_grabbed": 0}

        items, meta = self.prowlarr_client.fetch_rss(indexer_id, indexer_name, max_age_days=max_age_days, limit=limit)

        if meta["status"] == "rate_limited":
            retry_after_seconds = int(meta["retry_after_seconds"] or 0)
            self._update_state_fields(
                indexer_id=indexer_id,
                indexer_name=indexer_name,
                last_status="rate_limited",
                last_error=None,
                retry_not_before_at=now + timedelta(seconds=retry_after_seconds),
            )
            self._broadcast_indexer(indexer_id, indexer_name, "rate_limited", bootstrap=False, items_seen=0)
            return {"items_found": 0, "items_grabbed": 0}

        if meta["status"] == "error":
            self._update_state_fields(
                indexer_id=indexer_id,
                indexer_name=indexer_name,
                last_status="error",
                last_error=meta["error"],
                retry_not_before_at=None,
            )
            self._broadcast_indexer(indexer_id, indexer_name, "error", bootstrap=False, items_seen=0)
            return {"items_found": 0, "items_grabbed": 0}

        if state_row.last_poll_at is None:
            self._bootstrap_seen_items(indexer_id=indexer_id, items=items)
            bootstrap_seen = len(items)
            self._update_state_fields(
                indexer_id=indexer_id,
                indexer_name=indexer_name,
                last_poll_at=now,
                last_status="ok",
                last_error=None,
                retry_not_before_at=None,
                items_seen_delta=bootstrap_seen,
            )
            self._broadcast_indexer(indexer_id, indexer_name, "ok", bootstrap=True, items_seen=bootstrap_seen)
            return {"items_found": 0, "items_grabbed": 0}

        new_items = self._insert_new_seen_items(indexer_id=indexer_id, items=items)
        grabs = 0
        if new_items:
            grabs = self._match_and_grab(indexer_name=indexer_name, new_items=new_items)

        self._update_state_fields(
            indexer_id=indexer_id,
            indexer_name=indexer_name,
            last_poll_at=now,
            last_status="ok",
            last_error=None,
            retry_not_before_at=None,
            items_seen_delta=len(new_items),
            items_grabbed_delta=grabs,
        )
        self._broadcast_indexer(indexer_id, indexer_name, "ok", bootstrap=False, items_seen=len(new_items))
        return {"items_found": len(new_items), "items_grabbed": grabs}

    def _load_or_create_state(self, *, indexer_id: int, indexer_name: str) -> RssIndexerState:
        db = self._session_factory()
        try:
            state = db.get(RssIndexerState, indexer_id)
            if state is None:
                state = RssIndexerState(indexer_id=indexer_id, indexer_name=indexer_name)
                db.add(state)
                db.commit()
                db.refresh(state)
            elif cast(Any, state).indexer_name != indexer_name:
                cast(Any, state).indexer_name = indexer_name
                db.commit()
                db.refresh(state)
            else:
                db.expunge(state)
            return state
        finally:
            db.close()

    def _update_caps(
        self,
        *,
        indexer_id: int,
        indexer_name: str,
        supports_book_search: bool,
        cached_at: datetime,
    ) -> RssIndexerState:
        db = self._session_factory()
        try:
            state = self._get_or_create_state_in_session(db, indexer_id=indexer_id, indexer_name=indexer_name)
            state_row = cast(Any, state)
            state_row.indexer_name = indexer_name
            state_row.caps_cached_at = cached_at
            state_row.caps_supports_book_search = supports_book_search
            db.commit()
            db.refresh(state)
            db.expunge(state)
            return state
        finally:
            db.close()

    def _update_state_fields(
        self,
        *,
        indexer_id: int,
        indexer_name: str,
        last_poll_at: datetime | None = None,
        last_status: str | None = None,
        last_error: str | None = None,
        retry_not_before_at: datetime | None = None,
        items_seen_delta: int = 0,
        items_grabbed_delta: int = 0,
    ) -> None:
        db = self._session_factory()
        try:
            state = self._get_or_create_state_in_session(db, indexer_id=indexer_id, indexer_name=indexer_name)
            state_row = cast(Any, state)
            state_row.indexer_name = indexer_name
            if last_poll_at is not None:
                state_row.last_poll_at = last_poll_at
            if last_status is not None:
                state_row.last_status = last_status
            state_row.last_error = last_error
            state_row.retry_not_before_at = retry_not_before_at
            state_row.items_seen_count = int(state_row.items_seen_count or 0) + items_seen_delta
            state_row.items_grabbed_count = int(state_row.items_grabbed_count or 0) + items_grabbed_delta
            db.commit()
        finally:
            db.close()

    def _bootstrap_seen_items(self, *, indexer_id: int, items: list[dict]) -> int:
        db = self._session_factory()
        inserted = 0
        try:
            for item in items:
                guid = item.get("guid")
                if not guid:
                    continue
                db.add(RssSeenItem(indexer_id=indexer_id, guid=guid))
                try:
                    db.commit()
                    inserted += 1
                except IntegrityError:
                    db.rollback()
            return inserted
        finally:
            db.close()

    def _insert_new_seen_items(self, *, indexer_id: int, items: list[dict]) -> list[dict]:
        db = self._session_factory()
        new_items: list[dict] = []
        try:
            guids = [item.get("guid") for item in items if item.get("guid")]
            existing_guids = {
                guid
                for (guid,) in db.query(RssSeenItem.guid)
                .filter(RssSeenItem.indexer_id == indexer_id, RssSeenItem.guid.in_(guids))
                .all()
            }

            for item in items:
                guid = item.get("guid")
                if not guid or guid in existing_guids:
                    continue

                db.add(RssSeenItem(indexer_id=indexer_id, guid=guid))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    continue

                existing_guids.add(guid)
                new_items.append(item)

            return new_items
        finally:
            db.close()

    def _match_and_grab(self, *, indexer_name: str, new_items: list[dict]) -> int:
        db = self._session_factory()
        grabbed = 0
        try:
            books = (
                db.query(Book)
                .options(joinedload(Book.author))
                .filter(Book.status.in_([BookStatus.WANTED, BookStatus.MISSING]))
                .all()
            )

            for book in books:
                book_row = cast(Any, book)
                author_name = book_row.author.name if book_row.author else ""
                scored_results = self.search_service.evaluate_and_rank(
                    new_items,
                    query_title=str(book_row.title),
                    query_author=author_name,
                )
                approved_matches = [
                    scored
                    for scored in scored_results
                    if scored.approved
                    and (scored.title_similarity or 0.0) >= EPUB_TITLE_SIMILARITY_THRESHOLD
                    and scored.author_match is True
                ]
                if not approved_matches:
                    continue

                best_match = sorted(
                    approved_matches,
                    key=lambda scored: (
                        -(scored.title_similarity or 0.0),
                        -(scored.seeders or 0),
                        scored.age_days or 0.0,
                    ),
                )[0]
                matched_at = datetime.now(UTC).isoformat()

                self._broadcast(
                    "rss_match_found",
                    {
                        "book_id": int(book_row.id),
                        "indexer": indexer_name,
                        "guid": best_match.guid,
                        "title": best_match.title,
                        "matched_at": matched_at,
                        "similarity": best_match.title_similarity,
                    },
                )
                self._record_recent_match(
                    {
                        "book_id": int(book_row.id),
                        "indexer": indexer_name,
                        "guid": best_match.guid,
                        "title": best_match.title,
                        "matched_at": matched_at,
                        "similarity": best_match.title_similarity,
                    }
                )
                if self.pipeline_service.grab_known_result(book, best_match, db) == 1:
                    grabbed += 1
                    self._broadcast(
                        "rss_grabbed",
                        {"book_id": int(book_row.id), "indexer": indexer_name, "title": best_match.title},
                    )

            return grabbed
        finally:
            db.close()

    def _mark_indexer_error(self, *, indexer_id: int, indexer_name: str, error: str) -> None:
        if indexer_id <= 0:
            return
        self._update_state_fields(
            indexer_id=indexer_id,
            indexer_name=indexer_name,
            last_status="error",
            last_error=error,
        )
        self._broadcast_indexer(indexer_id, indexer_name, "error", bootstrap=False, items_seen=0)

    def _get_or_create_state_in_session(self, db: Any, *, indexer_id: int, indexer_name: str) -> RssIndexerState:
        state = db.get(RssIndexerState, indexer_id)
        if state is None:
            state = RssIndexerState(indexer_id=indexer_id, indexer_name=indexer_name)
            db.add(state)
            db.flush()
        return state

    def _record_recent_match(self, match: dict[str, Any]) -> None:
        self._recent_matches.append(match)
        if len(self._recent_matches) > 20:
            self._recent_matches = self._recent_matches[-20:]

    def _is_retry_in_future(self, retry_not_before_at: datetime | None, now: datetime) -> bool:
        if retry_not_before_at is None:
            return False
        return self._normalize_db_datetime(retry_not_before_at) > now

    def _is_caps_cache_fresh(self, cached_at: datetime, now: datetime, caps_cache_seconds: int) -> bool:
        return self._normalize_db_datetime(cached_at) >= now - timedelta(seconds=caps_cache_seconds)

    def _normalize_db_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def _broadcast_indexer(
        self,
        indexer_id: int,
        indexer_name: str,
        status: str,
        *,
        bootstrap: bool,
        items_seen: int,
    ) -> None:
        self._broadcast(
            "rss_indexer_polled",
            {
                "indexer_id": indexer_id,
                "indexer_name": indexer_name,
                "status": status,
                "bootstrap": bootstrap,
                "items_seen": items_seen,
            },
        )

    def _broadcast(self, event: str, data: dict[str, Any]) -> None:
        if self.ws_manager is not None:
            self.ws_manager.broadcast_sync(event, data)

    def _utcnow(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
