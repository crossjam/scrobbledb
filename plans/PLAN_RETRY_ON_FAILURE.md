# Implementation Plan: Retry on Failure for Last.fm API Calls

**Issue:** #27 - Implement retry on failure
**Status:** In Progress
**Started:** 2025-11-28

---

## Problem Statement

The scrobbledb ingestion process occasionally fails due to intermittent HTTP 500 errors from the Last.fm API. These failures occur during data fetching operations (e.g., at page 74 of 104), causing the entire ingest process to terminate. The system needs resilient retry logic with exponential backoff to handle these transient errors gracefully.

### Error Context
- **Error Type:** `pylast.WSError` with HTTP 500 status code
- **Affected Functions:**
  - `recent_tracks()` at line 122 in `src/scrobbledb/lastfm.py`
  - `recent_tracks_count()` at line 29 in `src/scrobbledb/lastfm.py`
- **Impact:** Complete ingestion failure on transient API errors

---

## Solution Design

### Approach
Implement retry logic using the `stamina` Python package, which provides:
- Exponential backoff strategy
- Configurable retry limits
- Built-in logging support
- Industry-standard retry patterns

### Implementation Requirements

1. **Package Dependency**
   - Add `stamina` to project dependencies in `pyproject.toml`

2. **Retry Configuration**
   - Max retries: 5 attempts (reasonable for transient errors)
   - Initial delay: 1 second
   - Backoff factor: 2 (exponential: 1s, 2s, 4s, 8s, 16s)
   - Total max time: ~31 seconds (1+2+4+8+16)

3. **Error Handling**
   - Catch: `pylast.WSError` (specifically HTTP 5xx errors)
   - Log: Each retry attempt with error details using loguru
   - Final failure: Re-raise exception after exhausting retries

4. **Affected Functions**
   - `recent_tracks()`: Wrap API request at line 122
   - `recent_tracks_count()`: Wrap API request at line 29

---

## Task Checklist

- [x] Create implementation plan document (2025-11-28)
- [x] Add `stamina` package to dependencies (2025-11-28)
- [x] Implement retry decorator/wrapper for API calls (2025-11-28)
- [x] Apply retry logic to `recent_tracks()` function (2025-11-28)
- [x] Apply retry logic to `recent_tracks_count()` function (2025-11-28)
- [x] Write unit tests for retry functionality (2025-11-28)
- [x] Run full test suite to ensure no regressions (2025-11-28)
- [x] Commit changes with descriptive message (2025-11-28)
- [x] Push to feature branch (2025-11-28)

---

## Implementation Details

### Stamina Usage Pattern

```python
import stamina

@stamina.retry(on=pylast.WSError, attempts=5, wait_initial=1.0, wait_max=16.0)
def api_call_with_retry():
    # API call here
    pass
```

Or using context manager:

```python
for attempt in stamina.retry_context(on=pylast.WSError, attempts=5):
    with attempt:
        # API call here
        pass
```

### Logging Integration

Stamina integrates with Python's logging system. We'll configure it to use loguru for consistent logging across the application:

- Log each retry attempt with attempt number
- Log backoff duration
- Log final success or failure

---

## Testing Strategy

1. **Unit Tests**
   - Mock `pylast.WSError` to simulate API failures
   - Verify retry attempts (count should match expected)
   - Verify exponential backoff delays
   - Verify final success after transient failures
   - Verify final exception after max retries exhausted

2. **Integration Consideration**
   - Manual testing with actual Last.fm API (optional)
   - Monitor logs during ingestion to verify retry behavior

---

## Implementation Progress

### 2025-11-28 - Initial Setup
- Created implementation plan
- Analyzed codebase and identified affected functions
- Defined retry strategy and configuration

### 2025-11-28 - Implementation Complete
- Added `stamina>=24.2.0` to project dependencies in `pyproject.toml`
- Created `_api_request_with_retry()` helper function in `src/scrobbledb/lastfm.py`
- Applied retry logic to `recent_tracks()` and `recent_tracks_count()` functions
- Wrote 8 comprehensive unit tests covering various retry scenarios
- All 146 tests passing (58 in test_lastfm_to_sqlite.py)
- Committed and pushed changes to feature branch

---

## Implementation Summary

### Changes Made

**1. Dependency Addition** (`pyproject.toml`)
- Added `stamina>=24.2.0` to project dependencies
- Package provides production-ready retry logic with exponential backoff

**2. Core Implementation** (`src/scrobbledb/lastfm.py`)
- Created `_api_request_with_retry()` helper function that wraps pylast API requests
- Configured retry behavior:
  - Maximum 5 attempts (initial + 4 retries)
  - Exponential backoff: 1s, 2s, 4s, 8s, 16s
  - Jitter of 1.0s to prevent thundering herd
  - Retries only on `pylast.WSError` exceptions
  - Other exceptions propagate immediately
- Integrated logging with loguru:
  - Debug-level logs for each attempt
  - Warning-level logs for failures
  - Info-level logs for eventual success after retries
- Updated `recent_tracks()` and `recent_tracks_count()` to use the retry wrapper

**3. Test Coverage** (`tests/test_lastfm_to_sqlite.py`)
- Added 8 new unit tests for retry functionality:
  - Success on first attempt (no unnecessary retries)
  - Success after single transient failure
  - Success after multiple transient failures
  - Exhaustion of all retry attempts
  - Non-WSError exceptions not retried
  - Integration with `recent_tracks_count()`
  - Integration with `recent_tracks()` generator
- All tests use mocking to simulate API behavior
- Tests verify correct retry counts and error handling

### Behavior

The implementation provides resilient API request handling:

1. **Transient Failures**: HTTP 500 errors and other `pylast.WSError` exceptions trigger automatic retry with exponential backoff
2. **Success Path**: Requests that succeed on first attempt incur no additional overhead
3. **Logging**: All retry attempts are logged for debugging and monitoring
4. **Final Failure**: After 5 failed attempts (total ~31s), the original exception is raised
5. **Non-Retryable Errors**: Programming errors and other exceptions fail fast without retry

### Testing Results

- **Total Tests**: 146 (all passing)
- **New Tests**: 8 retry-specific tests
- **Test Coverage**: Unit tests for retry logic, integration with existing functions
- **Execution Time**: ~44 seconds for full suite

### Benefits

1. **Reliability**: Ingestion processes no longer fail on transient API errors
2. **Performance**: Exponential backoff prevents overwhelming the API
3. **Observability**: Comprehensive logging aids in debugging and monitoring
4. **Maintainability**: Clean abstraction through helper function
5. **Standards**: Uses well-tested `stamina` library following industry best practices

### Known Limitations

- Retry logic only applies to Last.fm API requests (not other operations)
- Maximum retry time is ~31 seconds before final failure
- Backoff delays are fixed (not adaptive based on API response headers)

---

**Status**: ✅ Complete
**Date**: 2025-11-28

