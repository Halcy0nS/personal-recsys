# AGENTS.md

This document is the repository-specific operating guide for AI agents working in `/Users/salmon/Documents/python/personal-recsys/datacrawl`.

## 1. Ground Truth

- Treat the checked-in code artifacts as the only source of truth.
- The current snapshot does **not** contain the original `.py` source files for the crawler implementation.
- The business logic that is still available lives in compiled bytecode under:
  - `zhihu_crawler/__pycache__/`
  - `zhihu_crawler/utils/__pycache__/`
- This repository snapshot also does **not** include `requirements.txt`, even though the compiled `setup` entrypoint expects it.
- Sample crawler outputs and a persisted cookie file are present under `zhihu_crawler/data/`.

Do not infer missing behavior from file names alone. If a capability is not visible in the compiled modules or sample outputs, document it as unknown or absent.

## 2. Actual Architecture

### 2.1 Logical modules

The implementation is organized around these logical modules:

- `config`
  - Defines `CrawlConfig` and `ZhihuAuthConfig`.
  - Exposes global instances `crawl_config` and `auth_config`.
  - `ZhihuAuthConfig.__post_init__` reads `ZHIHU_USERNAME` and `ZHIHU_PASSWORD` from the environment.
- `models`
  - Defines the data structures `ZhihuAuthor`, `ZhihuContent`, `ZhihuCollection`, and `CrawlResult`.
  - `ZhihuContent` provides `to_dict()` and `to_json()`.
- `utils.saver`
  - Defines `DataSaver`.
  - Saves JSON and CSV, flattens nested dictionaries for CSV, and names files as `<prefix>_<YYYYMMDD_%H%M%S>.<ext>`.
- `utils.logger`
  - Configures `loguru` to write console output and `./logs/zhihu_crawler_{time:YYYY-MM-DD}.log`.
  - In the current snapshot, no other compiled module imports or uses this helper.
- `crawler`
  - Defines the base class `ZhihuCrawler`.
  - Owns Playwright lifecycle, cookie persistence, login checks, anti-detection injection, navigation retry logic, list parsing, deduplication, pagination, infinite-scroll fallback, and saving.
- `author_crawler`
  - Defines `AuthorCrawler(ZhihuCrawler)`.
  - Implements author-specific flows:
    - `crawl_author_answers`
    - `crawl_author_articles`
    - `crawl_author_all_content`
- `favorites_crawler`
  - Defines:
    - `FavoriteFolder`
    - `FavoritesCrawler(ZhihuCrawler)`
    - `create_crawler(headless=False)`
  - Implements favorites-list discovery, collection crawling, and optional detail-page enrichment for answers/articles.
- `run`
  - Defines `UnifiedCrawler(FavoritesCrawler, AuthorCrawler)`.
  - Provides the main interactive CLI and argparse CLI.
- `quickstart`
  - Provides preset menu-driven shortcuts for common flows.
- `setup`
  - Provides environment bootstrap helpers.
- `debug_collections`
  - Opens a fixed collections page and prints selector-debug information for manual inspection.

### 2.2 Module relationships

```text
models
  └─ shared dataclasses for all crawler flows

utils.saver
  └─ file output helper used by ZhihuCrawler

config
  └─ global crawl/auth settings referenced by crawler logic

ZhihuCrawler (base)
  ├─ AuthorCrawler
  └─ FavoritesCrawler

UnifiedCrawler = FavoritesCrawler + AuthorCrawler

run / quickstart / debug_collections / setup
  └─ command-line wrappers around the crawler classes
```

## 3. Responsibilities By Package/Directory

- `zhihu_crawler/__pycache__/`
  - Current location of the compiled business logic.
  - Contains logical modules such as `crawler`, `author_crawler`, `favorites_crawler`, `config`, `models`, `run`, `quickstart`, `setup`, and `debug_collections`.
- `zhihu_crawler/utils/__pycache__/`
  - Current location of compiled utility modules.
  - Contains `saver` and `logger`.
- `zhihu_crawler/data/`
  - Checked-in example outputs and `cookies.json`.
  - Example JSON records confirm the serialized schema of `ZhihuContent`.
- `zhihu_crawler/.venv/`
  - Local virtual environment snapshot; not part of the crawler architecture.
- `data/`
  - Empty in the current snapshot.
  - Still relevant because runtime defaults use `./data`, so output location depends on the working directory when commands are executed.
- `.claude/`
  - Local tool configuration for the workspace, not part of crawler runtime.

## 4. Runtime Behavior That Must Be Documented Accurately

- Browser automation is Playwright-based and synchronous (`playwright.sync_api`).
- Login is browser-assisted and manual:
  - `ZhihuCrawler.login()` opens `https://www.zhihu.com/signin`.
  - It instructs the user to log in manually in the browser.
  - Successful login saves cookies to `<data_dir>/cookies.json`.
- Cookie reuse is implemented:
  - `_load_cookies()` restores login state from the cookie file.
  - `_save_cookies()` persists it after login.
- Anti-detection logic is injected at browser startup by overriding `navigator.webdriver`, `navigator.plugins`, `navigator.languages`, and `window.chrome`.
- Navigation is resilient:
  - `_safe_goto()` retries failed page loads.
  - `_goto_next_page()` also has a fallback path for infinite scroll.
- Content parsing is list-page oriented by default.
  - The base parser `_parse_content_item()` infers `answer`, `article`, and `pin`.
  - It may return mixed content types from a single listing flow.
- Saving behavior:
  - `_save_contents()` uses `DataSaver.save_all_formats()`.
  - JSON preserves nested author objects and metadata.
  - CSV flattens nested fields into columns such as `author_id`, `author_name`, and so on.

## 5. Important Current Limitations

These are implementation facts in the current snapshot and should not be overstated.

- `ZhihuAuthConfig` loads environment variables, but no compiled runtime path currently references `auth_config`.
  - Do not claim the crawler performs automatic credential login.
- `ZhihuCollection` exists in `models`, but no compiled crawling flow currently uses it.
- `FavoriteFolder` includes `is_public: bool = True`, but `get_favorites_list()` does not populate it from page data.
- Favorites “positive/negative sample” language exists in UI strings, but the current `get_favorites_list()` implementation assigns `label = 1` to every discovered collection.
  - Sample output in `zhihu_crawler/data/favorites_cjm926_all_20260305_150447.json` matches this: all exported items have `metadata.label == 1`.
- Full-content enrichment exists only in the favorites API path via `fetch_full_content`.
  - Current CLI wrappers do not expose a flag for it.
  - The enrichment helpers implemented are `_extract_article_full_content()` and `_extract_answer_full_content()`. There is no dedicated full-content extractor for pins.
- The checked-in setup flow expects `requirements.txt`, but that file is missing in this snapshot.
- The checked-in implementation is bytecode-only, so direct source editing is not possible without recreating `.py` modules.

## 6. Entry Points

Logical entrypoints defined by the compiled modules:

- `run`
  - Interactive mode plus argparse flags:
    - `--headless`
    - `--favorites`
    - `--author`
    - `--type` with choices `answers`, `articles`, `all`
    - `--pages` default `5`
    - `--target-count` default `0`
- `quickstart`
  - Shortcut menu:
    - quick crawl favorites for `cjm926`
    - quick crawl author content
    - open full interactive menu
- `setup`
  - Checks Python version `>= 3.8`
  - installs `requirements.txt`
  - installs `playwright chromium`
  - creates `data/`
- `debug_collections`
  - Hardcodes `https://www.zhihu.com/people/cjm926/collections` for selector debugging

Because only compiled artifacts are checked in, do not promise that these entrypoints are directly runnable in a clean environment without restoring missing source/dependency files.

## 7. Data Contracts

### 7.1 `ZhihuAuthor`

Fields confirmed by the model and sample outputs:

- `id`
- `name`
- `url`
- `headline`
- `avatar_url`
- `follower_count`

### 7.2 `ZhihuContent`

Fields confirmed by the model and sample outputs:

- `id`
- `content_type`
- `title`
- `content`
- `excerpt`
- `author`
- `created_time`
- `updated_time`
- `voteup_count`
- `comment_count`
- `url`
- `metadata`

### 7.3 `CrawlResult`

Fields:

- `success`
- `message`
- `contents`
- `total_count`
- `saved_files`

### 7.4 Metadata differences by flow

- Author exports in the checked-in sample files use empty `metadata`.
- Favorites exports add:
  - `label`
  - `collection_url`

## 8. Rules For Future Changes

- Do not rewrite documentation as if plain `.py` sources exist unless they have actually been restored.
- If code work is requested in the future:
  - prefer recreating readable `.py` modules under `zhihu_crawler/` and `zhihu_crawler/utils/`
  - do not hand-edit `.pyc`
  - keep logical module names unchanged unless all entrypoints are updated consistently
- Preserve the actual import style when restoring source.
  - Current entrypoint modules modify `sys.path` and import siblings by bare module name such as `author_crawler`, `favorites_crawler`, `crawler`, `models`, and `config`.
- Be explicit about working-directory-sensitive paths.
  - `data_dir` defaults to `./data`
  - `cookies_file` defaults to `./data/cookies.json`
  - `utils.logger` writes to `./logs`
- Treat `cookies.json` as sensitive state and avoid committing fresh credentials or session data.
- When documenting favorites classification, state the current implementation truthfully: collection discovery currently labels everything as `1`.

## 9. Verification Checklist For Documentation Changes

Before changing project docs again, verify against code artifacts:

- module/class/function names from compiled modules
- dataclass fields from `models`
- CLI flags from `run`
- default config values from `config`
- output schema from files in `zhihu_crawler/data/`
- working-directory-relative paths for `data/`, `cookies.json`, and `logs/`

