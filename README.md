# Zhihu Crawler Snapshot

[简体中文](README_ZH.md)

## Overview

This repository snapshot contains a Playwright-based Zhihu crawler focused on two user-facing workflows:

- crawling a user's favorites collections
- crawling an author's answers and articles

The checked-in implementation is currently available as compiled Python bytecode under `zhihu_crawler/__pycache__/` and `zhihu_crawler/utils/__pycache__/`, plus sample output files under `zhihu_crawler/data/`.

## Current Repository State

This is important for anyone trying to run or extend the project:

- the original crawler `.py` source files are not present in this snapshot
- the logical modules still exist as compiled artifacts
- `zhihu_crawler/data/` contains example JSON/CSV outputs and a persisted `cookies.json`
- `zhihu_crawler/.venv/` is a local virtual environment snapshot, not part of the crawler architecture
- `setup` expects `requirements.txt`, but that file is not present in the current repository state

Because of that, this README documents the implemented architecture and behavior, but it does not assume a clean fresh setup is possible without restoring missing source/dependency files.

## Architecture

### Module map

| Logical module | Current checked-in location | Responsibility |
| --- | --- | --- |
| `config` | `zhihu_crawler/__pycache__/config.*.pyc` | Defines `CrawlConfig`, `ZhihuAuthConfig`, and global config instances |
| `models` | `zhihu_crawler/__pycache__/models.*.pyc` | Defines `ZhihuAuthor`, `ZhihuContent`, `ZhihuCollection`, `CrawlResult` |
| `utils.saver` | `zhihu_crawler/utils/__pycache__/saver.*.pyc` | Saves JSON/CSV output and flattens nested data for CSV |
| `utils.logger` | `zhihu_crawler/utils/__pycache__/logger.*.pyc` | Configures loguru output to console and `./logs/` |
| `crawler` | `zhihu_crawler/__pycache__/crawler.*.pyc` | Base Playwright crawler: browser lifecycle, login, cookies, navigation, parsing, deduplication, saving |
| `author_crawler` | `zhihu_crawler/__pycache__/author_crawler.*.pyc` | Author-specific crawling flows |
| `favorites_crawler` | `zhihu_crawler/__pycache__/favorites_crawler.*.pyc` | Favorites-list discovery and collection crawling |
| `run` | `zhihu_crawler/__pycache__/run.*.pyc` | Unified interactive/CLI entrypoint |
| `quickstart` | `zhihu_crawler/__pycache__/quickstart.*.pyc` | Shortcut menu for common flows |
| `setup` | `zhihu_crawler/__pycache__/setup.*.pyc` | Bootstrap helper |
| `debug_collections` | `zhihu_crawler/__pycache__/debug_collections.*.pyc` | Selector-debug helper for collections pages |

### Class relationships

```text
ZhihuCrawler
  ├─ AuthorCrawler
  └─ FavoritesCrawler

UnifiedCrawler = FavoritesCrawler + AuthorCrawler
```

### What each layer does

- `models` defines the shared data contracts returned by all crawl flows.
- `ZhihuCrawler` is the common browser/runtime layer.
- `AuthorCrawler` and `FavoritesCrawler` add page-specific navigation and extraction logic.
- `run` and `quickstart` are wrappers over those crawler classes.
- `DataSaver` turns in-memory results into JSON and CSV files.

## Implemented Features

### Base crawler behavior

The base crawler (`ZhihuCrawler`) implements:

- synchronous Playwright browser startup
- cookie loading and saving
- a manual login flow against `https://www.zhihu.com/signin`
- anti-detection script injection
- retrying page navigation through `_safe_goto()`
- list-item parsing into `ZhihuContent`
- page-level deduplication
- next-page navigation with infinite-scroll fallback
- saving results through `DataSaver`

### Author crawling

`AuthorCrawler` implements:

- `crawl_author_answers(author_id, max_pages=10, target_count=0)`
- `crawl_author_articles(author_id, max_pages=10, target_count=0)`
- `crawl_author_all_content(author_id, max_pages=10, target_count=0)`

Observed behavior from code and sample outputs:

- author pages are crawled from `/people/{author_id}/answers` and `/people/{author_id}/posts`
- the list parser can emit `answer`, `article`, and `pin`
- sample answer exports confirm that an "answers" crawl may still contain mixed content types because parsing is card-driven rather than hard-typed by workflow

### Favorites crawling

`FavoritesCrawler` implements:

- `get_favorites_list(username='cjm926')`
- `crawl_favorites(username='cjm926', max_pages=10, fetch_full_content=False)`
- `_crawl_single_collection(...)`
- optional detail-page enrichment for answers and articles

Important current limitation:

- the UI strings talk about positive/negative samples, but the checked-in `get_favorites_list()` implementation currently assigns `label = 1` to every collection it discovers
- the checked-in favorites sample export matches this: all exported items carry `metadata.label == 1`

## Data Model

### `ZhihuAuthor`

Fields:

- `id`
- `name`
- `url`
- `headline`
- `avatar_url`
- `follower_count`

### `ZhihuContent`

Fields:

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

### `CrawlResult`

Fields:

- `success`
- `message`
- `contents`
- `total_count`
- `saved_files`

### Output shape

Observed in `zhihu_crawler/data/`:

- JSON keeps nested `author` objects
- CSV flattens nested author fields into columns such as:
  - `author_id`
  - `author_name`
  - `author_url`
  - `author_headline`
  - `author_avatar_url`
  - `author_follower_count`
- favorites exports add `metadata.label` and `metadata.collection_url`
- author exports in the checked-in examples use empty `metadata`

## Configuration and State

### `CrawlConfig`

Default values defined by code:

- `headless=False`
- `data_dir='./data'`
- `cookies_file='./data/cookies.json'`
- `max_pages=10`
- `delay_between_requests=2.0`
- `max_retries=3`
- `debug_logging=False`

Default selectors include:

- content cards
- titles
- rich content blocks
- author name
- vote count
- comment count
- next-page button
- avatar

### `ZhihuAuthConfig`

The config object can read:

- `ZHIHU_USERNAME`
- `ZHIHU_PASSWORD`

But this is currently only defined in config; the runtime crawler flows do not consume `auth_config`, so login is still manual in the browser.

### Path behavior

Paths are working-directory-relative:

- crawler outputs default to `./data`
- cookies default to `./data/cookies.json`
- `utils.logger` writes to `./logs`

This matters because the repository currently contains both:

- `data/` at the repository root
- `zhihu_crawler/data/` inside the package directory

The checked-in sample outputs under `zhihu_crawler/data/` indicate that some runs were executed with `zhihu_crawler/` as the working directory.

## Entry Points Defined By Code

### `run`

The compiled `run` module defines:

- an interactive menu for:
  - favorites crawling
  - author answers
  - author articles
  - author all content
- argparse flags:
  - `--headless`
  - `--favorites`
  - `--author`
  - `--type {answers,articles,all}`
  - `--pages` with default `5`
  - `--target-count` with default `0`

### `quickstart`

The compiled `quickstart` module defines a shortcut menu for:

- quick favorites crawl for `cjm926`
- quick author crawl
- opening the full interactive menu

### `setup`

The compiled `setup` module:

- checks for Python `>= 3.8`
- tries to install dependencies from `requirements.txt`
- tries to install `playwright chromium`
- creates `data/`

In the current snapshot, `requirements.txt` is missing, so this setup path is documented but not complete.

### `debug_collections`

The compiled debug helper opens:

- `https://www.zhihu.com/people/cjm926/collections`

and prints selector-oriented diagnostics for collection cards.

## Repository Layout

```text
datacrawl/
├── .claude/
│   └── settings.local.json
├── data/
├── zhihu_crawler/
│   ├── .venv/
│   ├── __pycache__/
│   ├── data/
│   └── utils/
│       └── __pycache__/
├── AGENTS.md
├── CLAUDE.md
├── README.md
└── README_ZH.md
```

## Known Gaps In This Snapshot

- no plain `.py` crawler source files
- no `requirements.txt`
- `utils.logger` exists but is not wired into the current crawler flows
- `ZhihuCollection` exists as a model but is not used by the current crawl implementations
- favorites negative-sample classification is not implemented, despite the wording shown in UI strings
- favorites full-content fetching exists in the crawler API but is not exposed by the current CLI wrappers

## Documentation Basis

This README is derived strictly from:

- the compiled crawler modules currently checked into the repository
- the sample JSON/CSV files currently checked into `zhihu_crawler/data/`

It intentionally avoids describing behavior that cannot be confirmed from those artifacts.

