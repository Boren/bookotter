# Hardcover sync: search only newly added books

**Date:** 2026-08-04
**Status:** Approved

## Problem

When a Hardcover sync (scheduled poller in `backend/main.py` or manual endpoint via
`backend/api/routes/sync.py`) adds at least one new book, both call sites invoke
`pipeline.process_wanted_books()`, which searches **every** book in `wanted`/`missing`
status — not just the books the sync added. On the live instance, 20 unfindable wanted
books have accumulated up to 634 search attempts each, re-triggered every time any new
book arrives from Hardcover. This defeats the "no scheduled search spam" design
(commit `69acca7`).

Root cause: `HardcoverSyncService.sync_hardcover_lists()` knows the IDs of the books it
creates but returns only counts (`{"new_books": N, ...}`), so callers cannot target the
new books and fall back to searching everything.

## Design

### 1. `backend/services/hardcover_sync_service.py`

`sync_hardcover_lists()` collects the ID of each book it creates and adds
`new_book_ids: list[int]` to its result dict on **all** return paths:

- No lists / fetch error early-exits: `"new_book_ids": []`
- Normal path: IDs of books created in this run (append after the `db.commit()` that
  assigns the ID)

Existing keys (`new_books`, `existing_skipped`, `errors`) are unchanged; `new_books`
must equal `len(new_book_ids)` on the normal path.

### 2. `backend/api/routes/sync.py` — `_run_hardcover_sync_background`

Replace the `process_wanted_books()` call with a loop over the new IDs:

```python
grabbed = 0
for book_id in result["new_book_ids"]:
    grabbed += pipeline.search_single_book(book_id)
```

Gating is unchanged: only runs when `search_on_add` is true, there are new books, and
the pipeline service is initialized. `auto_searched` (grab count) and
`auto_search_error` result keys keep their semantics. `search_single_book` already
handles per-book errors, status checks, and logging.

### 3. `backend/main.py` — `_scheduled_hardcover_sync`

Delete the duplicated sync-then-search body. The scheduled job becomes a thin wrapper
that calls the shared helper `_run_hardcover_sync_background(app)` (imported from
`backend.api.routes.sync`) and logs its result dict. This removes the second copy of
the bug and prevents future drift between the two triggers.

## Behavior change

Books already sitting in `wanted`/`missing` are no longer re-searched when Hardcover
sync adds new books. The only remaining paths that search them:

- `POST /api/wanted/search-all` (`wanted.py`) — explicit bulk retry, unchanged
- `POST /api/search/auto/{id}` — explicit per-book search, unchanged
- Search-on-add for manual adds (`library.py`) — unchanged

## Testing (TDD)

1. `sync_hardcover_lists` result includes `new_book_ids` matching the created books;
   `[]` on early-exit paths.
2. `_run_hardcover_sync_background` with new books calls `search_single_book` once per
   new ID and never calls `process_wanted_books`; pre-existing wanted books are
   untouched.
3. `_run_hardcover_sync_background` with zero new books performs no searches.
4. Scheduled poller registers a job that delegates to the shared helper (verify by
   patching the helper).
5. Update existing sync tests for the new result key.

## Out of scope

- The 20 currently-stuck wanted books (Norwegian titles / rejected results) — separate
  concern.
- Approval-filter tuning for books with `0/N approved` results.
- RSS sync enablement.
