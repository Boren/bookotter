# Omnibus Release Guard — Design

**Date:** 2026-08-07
**Status:** Approved

## Problem

When searching indexers for a single volume, the author-match rescue in
`SearchService._evaluate` (backend/services/search_service.py) keeps
same-author releases alive even when title similarity is low. If no proper
single-volume release exists, auto-grab takes an omnibus ("The First Law
Trilogy" while wanting "The Blade Itself"). The library then holds a bundle
where a split series belongs, producing duplicate series positions and wrong
Kindle/series grouping.

Real cases cleaned up on 2026-08-07: The First Law Trilogy, Mistborn Trilogy,
two Hitchhiker's "Authorized Collection" editions.

## Scope

Release-selection layer only. Hardcover sync and scanner imports are out of
scope (user-driven; decided during brainstorming). Hard rejection, not a
ranking penalty. No config toggle, no UI change, no migration.

## Design

### Detection

In `backend/services/search_service.py`, next to `AUDIOBOOK_RE`:

- `OMNIBUS_SIGNAL_RES: dict[str, re.Pattern]` — named, case-insensitive,
  word-boundary patterns:
  - `omnibus`: `\bomnibus\b`
  - `trilogy`: `\btrilogy\b`
  - `duology`: `\bduology\b`
  - `quadrilogy`: `\bquadrilogy\b`
  - `box-set`: `\bbox(ed)?[ -]?set\b`
  - `collection`: `\bcollection\b`
  - `anthology`: `\banthology\b`
  - `complete-series`: `\bcomplete series\b`
  - `book-range`: `\bbooks?\s*\d+\s*[-–—]\s*\d+\b`
  - `hash-range`: `#\d+\s*[-–—]\s*\d+`
  - `vol-range`: `\bvol(ume)?s?\.?\s*\d+\s*[-–—]\s*\d+\b`
- Helper `omnibus_signals(text: str) -> set[str]` returns the names of
  patterns that match. Comparing by pattern *name* (not matched text) means
  numeric ranges compare as a class.

### Rejection (query-aware)

In `_evaluate`, after the audiobook check:

```python
if query_title:
    release_signals = omnibus_signals(title) - omnibus_signals(query_title)
    if release_signals:
        rejections.append("Omnibus/collection")
```

- Signals present in the query title are suppressed: searching for
  "Arcanum Unbounded: The Cosmere Collection" still accepts
  collection-tagged releases.
- Empty `query_title` (bare `filter_results`/`rank_results` calls) skips the
  guard — no query context, no judgment.
- Manual `/grab` is unaffected: rejected results remain visible in manual
  search with the rejection reason; grab does not consult rejections.

### Coverage

All auto paths funnel through `_evaluate` with a query title: pipeline
auto-search (`pipeline_service.py:753`), manual/auto search routes
(`api/routes/search.py`), RSS sync (`rss_sync_service.py:380`). One guard
covers all of them.

## Error handling

None needed beyond existing flow — detection is pure regex over strings
already guaranteed non-None (`title = raw.get("title") or ""`). A release
wrongly rejected can still be grabbed manually, and the rejection string in
the UI explains why it was skipped.

## Testing

Extend `tests/test_search_service_rejections.py` (pure `_evaluate` tests, no
DB/network):

1. "The First Law Trilogy [EPUB]" vs query "The Blade Itself" → rejected
   ("Omnibus/collection").
2. "Mistborn Trilogy" vs "Mistborn: The Final Empire" → rejected.
3. "Dungeon Crawler Carl Books 1-7" vs "This Inevitable Ruin" → rejected
   (numeric range).
4. Suppression: "Arcanum Unbounded: The Cosmere Collection EPUB" vs query
   "Arcanum Unbounded: The Cosmere Collection" → approved.
5. Control: "The Blade Itself (2006) EPUB" vs "The Blade Itself" → approved.
6. No query title → guard inert (existing filter_results behavior
   unchanged).
