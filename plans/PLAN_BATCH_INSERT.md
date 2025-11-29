# Plan: Implement Batch Insert

## Issue Summary
The `ingest` command in `cli.py` currently inserts track information individually into the SQLite database. This should be optimized using batch inserts via sqlite-utils `insert_all`/`upsert_all` functions for better performance.

## Requirements
- Support specifying chunk size via `--batch-size` command line option
- Default batch size of 100 records
- Use sqlite-utils `upsert_all` for bulk inserts

## Implementation Steps

### 1. Add Command Line Option
- [x] Add `--batch-size` option to `ingest` command in `cli.py`
- [x] Default value: 100

### 2. Create Batch Save Functions in `lastfm.py`
- [x] Add `save_artists_batch(db, artists)` function using `upsert_all`
- [x] Add `save_albums_batch(db, albums)` function using `upsert_all`
- [x] Add `save_tracks_batch(db, tracks)` function using `upsert_all`
- [x] Add `save_plays_batch(db, plays)` function using `upsert_all`

### 3. Modify Ingest Loop in `cli.py`
- [x] Collect records into batches
- [x] Call batch save functions when batch is full
- [x] Flush remaining records after loop completes

### 4. Testing
- [x] Add tests for batch functions
- [x] Add tests for batch size option
- [x] Verify existing tests still pass

## Technical Details

### sqlite-utils Bulk Insert API
Reference: https://sqlite-utils.datasette.io/en/stable/python-api.html#bulk-inserts

```python
# For upsert_all with primary key:
db["table"].upsert_all(
    records,
    pk="id",
    column_order=[...],
    not_null=[...],
    batch_size=100
)
```

### Batch Processing Pattern
```python
batch = {"artists": [], "albums": [], "tracks": [], "plays": []}
for track in history:
    batch["artists"].append(track["artist"])
    batch["albums"].append(track["album"])
    batch["tracks"].append(track["track"])
    batch["plays"].append(track["play"])
    
    if len(batch["plays"]) >= batch_size:
        flush_batch(db, batch)
        batch = {"artists": [], "albums": [], "tracks": [], "plays": []}

# Flush remaining
if batch["plays"]:
    flush_batch(db, batch)
```

## Status: COMPLETE ✅
All implementation steps have been completed and tests pass.
