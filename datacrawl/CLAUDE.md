# CLAUDE.md

This file is the Claude-compatible quick guide for this repository. `AGENTS.md` is the more complete, authoritative version; keep the two consistent.

## Snapshot Facts

- The current crawler implementation is checked in as compiled bytecode, not plain `.py` source.
- Core logic lives in:
  - `zhihu_crawler/__pycache__/`
  - `zhihu_crawler/utils/__pycache__/`
- Sample outputs and persisted cookies live in `zhihu_crawler/data/`.
- `setup` expects `requirements.txt`, but that file is not present in the current snapshot.

## Architecture

- `config`
  - `CrawlConfig`, `ZhihuAuthConfig`, `crawl_config`, `auth_config`
- `models`
  - `ZhihuAuthor`, `ZhihuContent`, `ZhihuCollection`, `CrawlResult`
- `utils.saver`
  - `DataSaver` for JSON/CSV output
- `utils.logger`
  - loguru setup helper; not imported by the current crawler flows
- `crawler`
  - `ZhihuCrawler`: Playwright lifecycle, cookies, login checks, navigation retries, parsing, deduplication, pagination, saving
- `author_crawler`
  - `AuthorCrawler(ZhihuCrawler)`
- `favorites_crawler`
  - `FavoritesCrawler(ZhihuCrawler)`, `FavoriteFolder`, `create_crawler`
- `run`
  - `UnifiedCrawler(FavoritesCrawler, AuthorCrawler)` plus interactive/CLI entrypoints
- `quickstart`
  - preset shortcuts
- `setup`
  - bootstrap helper
- `debug_collections`
  - selector-debug helper for the collections page

## Current Behavioral Truths

- Login is manual in the browser, not automated credential login.
- Cookies are loaded from and saved to `<data_dir>/cookies.json`.
- Output defaults are relative to the current working directory:
  - `./data`
  - `./logs`
- `ZhihuAuthConfig` reads `ZHIHU_USERNAME` and `ZHIHU_PASSWORD`, but `auth_config` is not used by the current runtime flows.
- Favorites labeling is not fully implemented in the checked-in code:
  - UI text mentions positive/negative samples
  - actual collection discovery currently assigns `label = 1` to every folder
- Favorites full-content enrichment exists only at the API level (`fetch_full_content`) and is not exposed by the current CLI wrappers.
- `ZhihuCollection` exists as a model but is not used by the current crawling flows.

## Data Contracts

Confirmed export schema for `ZhihuContent`:

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

Confirmed nested `author` fields:

- `id`
- `name`
- `url`
- `headline`
- `avatar_url`
- `follower_count`

Favorites exports additionally use `metadata.label` and `metadata.collection_url`.

## Safe Editing Guidance

- Do not hand-edit `.pyc` files.
- If code restoration is needed, recreate readable `.py` files under the same logical module names.
- Do not document missing files as if they exist.
- Preserve the current module boundaries and inheritance:
  - `AuthorCrawler -> ZhihuCrawler`
  - `FavoritesCrawler -> ZhihuCrawler`
  - `UnifiedCrawler -> FavoritesCrawler + AuthorCrawler`
- Be precise about path sensitivity and the missing `requirements.txt`.

