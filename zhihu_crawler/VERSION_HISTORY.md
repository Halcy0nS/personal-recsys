# Version History (Zhihu Crawler)

## v0.1.0 - Baseline Crawler
Date: 2026-03-05

### Scope
- Initial runnable crawler for favorites and author content.
- JSON/CSV export and quickstart entry.

### Key Components
- `crawler.py`: browser/session/login, basic parse and save helpers.
- `favorites_crawler.py`: collection crawl flow.
- `author_crawler.py`: author answers/articles/all flow.
- `run.py` and `quickstart.py`: CLI + quick menu.

### Known Gaps
- Author/favorites shared capability was incomplete.
- Pagination behavior diverged across pages with different UI models.


## v0.2.0 - Shared Pipeline Fix
Date: 2026-03-05

### Scope
- Fix blocking error in favorites crawl:
  - `'FavoritesCrawler' object has no attribute '_goto_next_page'`

### Changes
- Moved shared methods to base crawler:
  - `_extract_page_contents`
  - `_goto_next_page`
  - `_save_contents`
  - `_get_console`
- Aligned favorites and author flows to reuse shared methods.
- Kept CLI parameters/output structure stable.

### Result
- Favorites crawl resumed and could continue across pages.


## v0.3.0 - Infinite Scroll Fallback + Diagnostics
Date: 2026-03-05

### Scope
- Diagnose author `/posts` and `/answers` where next-page button is absent.

### Changes
- Added detailed diagnostics:
  - selector hit counts
  - candidate element state
  - navigation snapshots
- Added no-button fallback:
  - `_try_infinite_scroll_load`
  - load-more click + scroll probing

### Result
- Author crawling no longer stopped at page 1 when UI used infinite scroll.


## v0.4.0 - Full Crawl Mode
Date: 2026-03-05

### Scope
- Introduce all-content mode semantics:
  - `max_pages <= 0` means unlimited crawl.

### Changes
- Reworked author loops from fixed `for range` to `while True`.
- Unified stop reasons:
  - `max_pages`
  - `no_new_rounds`
  - `no_next_and_no_new`
  - `hard_cap`
- Set quickstart author default to full mode.

### Result
- Author crawl could go beyond fixed page caps.


## v0.5.0 - Performance + Stability Pass
Date: 2026-03-05 to 2026-03-09

### Scope
- Improve long-run crawl performance and operational reliability.

### Changes
- Incremental extraction window:
  - overlap strategy for boundary safety
  - tail-window strategy when list length does not grow
- URL normalization to avoid malformed double-domain links.
- Debug log gate controlled by config/env switch.
- Added `target_count` stop option for controlled runs.

### Result
- Significant runtime reduction versus full-page reparse.
- Stable run-to-target (`500` records) and full runs completed.

### Remaining Risks
- Type classification in answers flow can still over-classify non-answer cards.
- Tail-end convergence may still miss a small fraction near profile counters.


## Versioning Rules (from now on)

### Semantic Intent
- Major: crawl model/interface breaking changes.
- Minor: new capabilities (new stop mode, new retrieval path).
- Patch: bug fixes, parser updates, stability/perf tuning.

### Release Checklist
1. Run smoke commands:
   - `run.py --author <id> --type answers --pages 1`
   - `run.py --author <id> --type articles --pages 1`
   - `run.py --favorites <id> --pages 1`
2. Confirm JSON/CSV output paths and basic field completeness.
3. Update this file with:
   - scope
   - changes
   - result
   - known gaps
