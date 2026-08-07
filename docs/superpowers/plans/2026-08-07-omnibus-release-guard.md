# Omnibus Release Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-reject omnibus/collection releases in indexer search when the query is for a single volume, so auto-grab never picks a bundle.

**Architecture:** Pure-regex detection (`OMNIBUS_SIGNAL_RES` + `omnibus_signals()`) at module level in `backend/services/search_service.py`, wired into `SearchService._evaluate` as one new rejection reason. Signals present in the query title are subtracted from the release's signals, so wanted books that are themselves collections are unaffected. Spec: `docs/superpowers/specs/2026-08-07-omnibus-release-guard-design.md`.

**Tech Stack:** Python 3.14, pytest, `re` stdlib only. Run everything with `uv run` (system python3 is not 3.14).

## Global Constraints

- Rejection string is exactly `"Omnibus/collection"`.
- Guard only runs when `query_title` is non-empty.
- No config toggle, no UI change, no DB migration.
- Never reference AI tooling artifacts in code, comments, or commits.
- Branch: `feat/omnibus-release-guard` (already exists, spec committed).

---

### Task 1: Signal detection — `omnibus_signals()`

**Files:**
- Modify: `backend/services/search_service.py` (module level, after `AUDIOBOOK_RE` block ending line 31)
- Test: `tests/test_search_service_rejections.py` (append new class)

**Interfaces:**
- Produces: `omnibus_signals(text: str) -> set[str]` returning names from `OMNIBUS_SIGNAL_RES` (keys: `omnibus`, `trilogy`, `duology`, `quadrilogy`, `box-set`, `collection`, `anthology`, `complete-series`, `book-range`, `hash-range`, `vol-range`). Importable as `from backend.services.search_service import omnibus_signals`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_search_service_rejections.py`:

```python
class TestOmnibusSignals:
    def test_phrase_signals_detected(self):
        from backend.services.search_service import omnibus_signals

        assert omnibus_signals("The First Law Trilogy EPUB") == {"trilogy"}
        assert omnibus_signals("Sherlock Holmes Omnibus") == {"omnibus"}
        assert omnibus_signals("The Cosmere Collection") == {"collection"}
        assert omnibus_signals("Complete Series Boxed Set") == {"complete-series", "box-set"}

    def test_numeric_range_signals_detected(self):
        from backend.services.search_service import omnibus_signals

        assert omnibus_signals("Dungeon Crawler Carl Books 1-7") == {"book-range"}
        assert omnibus_signals("First Law #1-3 EPUB") == {"hash-range"}
        assert omnibus_signals("Mistborn Vols. 1-3") == {"vol-range"}

    def test_clean_titles_have_no_signals(self):
        from backend.services.search_service import omnibus_signals

        assert omnibus_signals("The Blade Itself (2006) EPUB") == set()
        assert omnibus_signals("This Inevitable Ruin - Book 7") == set()
        assert omnibus_signals("") == set()
```

Note: single volume markers ("Book 7", "#07") must NOT match the range patterns — that is what `test_clean_titles_have_no_signals` pins down.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_search_service_rejections.py::TestOmnibusSignals -v`
Expected: FAIL / ERROR with `ImportError: cannot import name 'omnibus_signals'`

- [ ] **Step 3: Implement detection**

In `backend/services/search_service.py`, insert after the `AUDIOBOOK_RE` definition (after line 31, before `AUDIO_CATEGORY_RANGE`):

```python
# Omnibus/collection detection.
# Named patterns so query and release signals compare as classes: a query
# containing "Books 1-3" suppresses any book-range signal in a release,
# not just the identical text. Ranges require an explicit N-M span so
# single-volume markers ("Book 7") never match.
OMNIBUS_SIGNAL_RES: dict[str, re.Pattern] = {
    "omnibus": re.compile(r"\bomnibus\b", re.IGNORECASE),
    "trilogy": re.compile(r"\btrilogy\b", re.IGNORECASE),
    "duology": re.compile(r"\bduology\b", re.IGNORECASE),
    "quadrilogy": re.compile(r"\bquadrilogy\b", re.IGNORECASE),
    "box-set": re.compile(r"\bbox(?:ed)?[ -]?set\b", re.IGNORECASE),
    "collection": re.compile(r"\bcollection\b", re.IGNORECASE),
    "anthology": re.compile(r"\banthology\b", re.IGNORECASE),
    "complete-series": re.compile(r"\bcomplete series\b", re.IGNORECASE),
    "book-range": re.compile(r"\bbooks?\s*\d+\s*[-–—]\s*\d+\b", re.IGNORECASE),
    "hash-range": re.compile(r"#\d+\s*[-–—]\s*\d+"),
    "vol-range": re.compile(r"\bvol(?:ume)?s?\.?\s*\d+\s*[-–—]\s*\d+\b", re.IGNORECASE),
}


def omnibus_signals(text: str) -> set[str]:
    """Names of omnibus/collection markers present in a release or query title."""
    return {name for name, pattern in OMNIBUS_SIGNAL_RES.items() if pattern.search(text)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_search_service_rejections.py::TestOmnibusSignals -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/search_service.py tests/test_search_service_rejections.py
git commit -m "feat(search): omnibus/collection signal detection"
```

---

### Task 2: Query-aware rejection in `_evaluate`

**Files:**
- Modify: `backend/services/search_service.py:129-133` (inside `_evaluate`, after the audiobook check)
- Test: `tests/test_search_service_rejections.py` (append new class)

**Interfaces:**
- Consumes: `omnibus_signals(text: str) -> set[str]` from Task 1 (same module, no import needed).
- Produces: `"Omnibus/collection"` entry in `ScoredResult.rejections`; `approved` flips false via the existing `len(rejections) == 0` logic. No signature changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_search_service_rejections.py`. The author kwarg matters: without it these releases already fail on "No candidate matches title" (low title similarity, no author match); the author-match rescue is exactly the hole being closed.

```python
class TestOmnibusRejection:
    def test_trilogy_rejected_for_single_volume_query(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="The First Law Trilogy by Joe Abercrombie EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "The Blade Itself", author="Joe Abercrombie"
        )

        assert results[0].rejections == ["Omnibus/collection"]
        assert results[0].approved is False

    def test_mistborn_trilogy_rejected(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Mistborn Trilogy by Brandon Sanderson EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "Mistborn: The Final Empire", author="Brandon Sanderson"
        )

        assert "Omnibus/collection" in results[0].rejections

    def test_book_range_rejected_for_single_volume_query(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Matt Dinniman - Dungeon Crawler Carl Books 1-7 EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "This Inevitable Ruin", author="Matt Dinniman"
        )

        assert "Omnibus/collection" in results[0].rejections

    def test_query_signal_suppressed(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Arcanum Unbounded: The Cosmere Collection EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "Arcanum Unbounded: The Cosmere Collection", author="Brandon Sanderson"
        )

        assert results[0].approved is True
        assert results[0].rejections == []

    def test_single_volume_release_not_rejected(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="The Blade Itself by Joe Abercrombie EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "The Blade Itself", author="Joe Abercrombie"
        )

        assert results[0].approved is True

    def test_no_query_title_skips_guard(self, db_session):
        prowlarr = MagicMock()
        service = SearchService(prowlarr, db_session)

        filtered = service.filter_results([make_result(title="The First Law Trilogy EPUB")])

        assert len(filtered) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_search_service_rejections.py::TestOmnibusRejection -v`
Expected: `test_trilogy_rejected_for_single_volume_query` and `test_book_range_rejected_for_single_volume_query` FAIL (release is approved / wrong rejections); the other three PASS (they pin current behavior).

- [ ] **Step 3: Wire the rejection**

In `_evaluate` in `backend/services/search_service.py`, directly after the audiobook check (`if AUDIOBOOK_RE.search(title): rejections.append("Audiobook")`), insert:

```python
        if query_title:
            release_only_signals = omnibus_signals(title) - omnibus_signals(query_title)
            if release_only_signals:
                rejections.append("Omnibus/collection")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_search_service_rejections.py -v`
Expected: all PASS (new classes and all pre-existing rejection tests).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS. If any pre-existing test constructed a query or release title containing a signal word, fix the *test expectation only if* the new rejection is correct behavior for it; otherwise revisit the pattern list.

- [ ] **Step 6: Commit**

```bash
git add backend/services/search_service.py tests/test_search_service_rejections.py
git commit -m "feat(search): hard-reject omnibus releases for single-volume queries"
```
