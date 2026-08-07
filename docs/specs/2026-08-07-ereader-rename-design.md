# E-reader Rename Design

Rename every "Kindle" reference to the vendor-agnostic "ereader" — UI text, code
identifiers, API routes, config keys, and persisted database state. Persisted
state migrates via a one-shot CLI command run manually at deploy time.

## Goals

- No user-visible or internal reference to the Kindle brand remains.
- One manual migration step at deploy time (`docker exec`), nothing else.
- Impossible to boot the new version against unmigrated data and silently
  lose delivery state (which would trigger mass re-send/mass-delete in the
  mirror sync).

## Naming conventions

| Layer | Old | New |
|---|---|---|
| UI text | Kindle | E-reader / E-readers |
| Python modules | `kindle_client.py`, `kindle_delivery.py`, `kindles.py` | `ereader_client.py`, `ereader_delivery.py`, `ereaders.py` |
| Classes/enums | `KindleClient`, `KindleDeliveryStatus` | `EreaderClient`, `EreaderDeliveryStatus` |
| Vue | `KindleView.vue`, `components/kindle/*`, `stores/kindles.ts` | `EreaderView.vue`, `components/ereader/*`, `stores/ereaders.ts` |
| CSS | `.kindle-*` | `.ereader-*` |
| API routes | `/api/kindles`, `/books/{id}/kindle-requeue` | `/api/ereaders`, `/books/{id}/ereader-requeue` |
| WS events / job IDs | `kindle_sync_*`, `kindle_auto_sync` | `ereader_sync_*`, `ereader_auto_sync` (scheduler is MemoryJobStore — nothing persisted) |
| Config keys | `kindles:`, `kindle_sync:`, `kindle_sync_on_import` | `ereaders:`, `ereader_sync:`, `ereader_sync_on_import` |
| DB columns (books) | `kindle_delivery_status`, `kindle_delivery_attempts`, `kindle_first_pending_at`, `kindle_delivered_at`, `kindle_pinned` | same names with `ereader_` prefix |
| Persisted category strings | `kindle_unreachable`, `kindle_auth_failed`, `kindle_disk_full`, `kindle_transfer_failed` | same with `ereader_` prefix, in both the `FailureCategory` enum and stored `failure_reason` / `failure_history` values |
The DB and log files are already `bookotter.db` / `bookotter.log` (verified in
code and on the live instance); the `data/kindlesync.db` in the working tree is
a stale leftover from an old version and is deleted, not migrated.

`to_dict()` key changes mean the API response shape changes; frontend and
backend ship together in one image, so no compatibility layer is needed.

## Migration command

`python -m backend.cli migrate-to-ereader` — an argparse subcommand in the
existing `backend/cli.py`. Because adding subcommands changes the CLI's
current single-purpose invocation, the existing sync flow becomes the default
subcommand so existing invocations keep working.

Steps, in order:

1. **Backup**: copy `bookotter.db` → `bookotter.db.bak-ereader` and
   `config.yaml` → `config.yaml.bak-ereader`. Refuse to overwrite an existing
   backup (previous half-completed run) unless `--force`.
2. **Column renames**: `ALTER TABLE books RENAME COLUMN kindle_* TO ereader_*`
   for the five columns, each guarded by "old column exists".
3. **Data rewrite**: `UPDATE books SET failure_reason = 'ereader_…'` for the
   four category strings, and rewrite occurrences inside the
   `failure_history` JSON column.
4. **Config rewrite**: rename the three config keys, preserving values and
   unknown keys. Also handles the pre-multi-kindle legacy `kindle:` key
   (folding in what `_migrate_kindle_config` does today, which is then
   removed from the load path).

Properties:

- **Idempotent**: every step is guarded by an existence check; re-running on
  a migrated system is a no-op that reports "already migrated".
- **`--dry-run`**: prints each step's would-be action and exits without
  touching anything.
- **Fresh installs**: no old DB and no old config keys → nothing to do; new
  installs simply start on the new names.

## Startup guard

At startup — critically, **before** `_apply_pending_column_migrations` in
`backend/database.py` — fail fast with a clear error naming the migration
command if either:

- the `books` table still has any `kindle_*` column, or
- the loaded config contains `kindles`/`kindle_sync`/`kindle_sync_on_import`
  (or legacy `kindle`) keys.

Ordering matters: the column-add helper would otherwise auto-create the five
`ereader_*` columns as fresh empty ones next to the old data. Empty
`ereader_pinned` and delivery-status columns make the mirror sync treat every
book as unpinned and never delivered — the mass re-send/mass-delete scenario.

## Code rename scope

Pure rename everywhere else: backend modules/identifiers, all Vue components
and stores, the 15+ `test_kindle_*` test files (renamed and updated), README,
AGENTS.md, docker-compose comments, CHANGELOG (new entry marked breaking,
with the migration command; history entries untouched). Comment prose saying
"Kindle" becomes "e-reader" except where it states a device-specific fact
(e.g. the `mv` atomicity probe result), which keeps its meaning but loses the
brand name where possible. `docs/probes/kindle-rename.md` and
`scripts/probe_kindle_rename.py` are renamed to `ereader-*` with contents
updated.

## Testing

- Migration command: fresh install (no-op), full old-state fixture (DB file +
  columns + category strings + config keys), already-migrated (no-op),
  `--dry-run` (no side effects), half-migrated re-run (completes the rest).
- Startup guard: old DB present → refuses to boot; migrated → boots.
- All existing renamed tests pass; `test_api_response_shape.py` asserts the
  new `ereader_*` keys.

## Deploy (unraid)

The startup guard means the new image won't stay up against old data, so the
migration runs as a one-off container with the same data mount, not via
`docker exec` into a crashed container:

1. Push dev → CI builds ghcr `:dev` → `docker pull` on unraid; stop and
   remove the running container.
2. `docker run --rm -v /mnt/cache/appdata/bookotter:/app/data:rw ghcr.io/boren/bookotter:dev python -m backend.cli migrate-to-ereader --dry-run`, then without `--dry-run`.
3. Recreate the container on the new image (usual `docker run` config).

Rollback: stop the container, restore `bookotter.db.bak-ereader` and
`config.yaml.bak-ereader`, run the previous image.

