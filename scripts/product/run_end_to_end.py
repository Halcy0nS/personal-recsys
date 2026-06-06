"""Run the end-to-end MVP workflow: crawler outputs -> local recommendation MVP."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


DEFAULT_PAGES = 0
DEFAULT_TOP_K = 20
DEFAULT_CRAWLER_PYTHON = "datacrawl/zhihu_crawler/.venv/bin/python"
DEFAULT_CRAWLER_WORKDIR = "datacrawl/zhihu_crawler"
DEFAULT_OUTPUT_DIR = "data/experiments/mvp_runs/latest"
DEFAULT_CACHE_DIR = "data/cache/mvp"


class EndToEndError(RuntimeError):
    """User-facing end-to-end CLI error."""


console = Console()
error_console = Console(stderr=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--favorites-user")
    parser.add_argument("--author-id")
    parser.add_argument("--pages", type=int)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--crawler-python", default=DEFAULT_CRAWLER_PYTHON)
    parser.add_argument("--crawler-workdir", default=DEFAULT_CRAWLER_WORKDIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    return parser.parse_args()


def _log(message: str) -> None:
    console.print(f"[bold cyan][E2E][/bold cyan] {message}")


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _check_path_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise EndToEndError(f"{label} not found: {path}")


def _normalize_cli_path(raw_path: str, *, repo_root: Path, resolve_symlinks: bool) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve() if resolve_symlinks else path.absolute()


def _show_interactive_banner() -> None:
    console.print(
        Panel.fit(
            "知乎爬虫 -> 本地推荐 MVP\n缺少关键参数时将进入交互补全。",
            title="Interactive Product CLI",
            border_style="cyan",
        )
    )


def _prompt_non_empty(label: str, default: str | None = None) -> str:
    prompt = label if default is None else f"{label} [dim](默认: {default})[/dim]"
    while True:
        value = console.input(f"{prompt}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        console.print("[red]输入不能为空，请重试。[/red]")


def _prompt_int(label: str, *, default: int, minimum: int) -> int:
    prompt = f"{label} [dim](默认: {default})[/dim]"
    while True:
        raw = console.input(f"{prompt}: ").strip()
        if not raw:
            return default
        if raw.isdigit():
            value = int(raw)
            if value >= minimum:
                return value
        console.print(f"[red]请输入大于等于 {minimum} 的整数。[/red]")


def _confirm_interactive_run(args: argparse.Namespace) -> None:
    table = Table(title="即将开始的一键抓取与推荐", show_header=True, header_style="bold magenta")
    table.add_column("参数", style="cyan")
    table.add_column("值", style="green")
    table.add_row("favorites_user", args.favorites_user)
    table.add_row("author_id", args.author_id)
    table.add_row("pages", str(args.pages))
    table.add_row("top_k", str(args.top_k))
    table.add_row("crawler_python", str(args.crawler_python))
    table.add_row("crawler_workdir", str(args.crawler_workdir))
    table.add_row("output_dir", str(args.output_dir))
    table.add_row("cache_dir", str(args.cache_dir))
    console.print(table)
    confirm = console.input("确认开始? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        raise EndToEndError("Interactive run cancelled by user.")


def _resolve_interactive_args(args: argparse.Namespace) -> argparse.Namespace:
    stdin_is_tty = sys.stdin.isatty()
    interactive_needed = any(
        getattr(args, field) in (None, "")
        for field in ("favorites_user", "author_id", "pages", "top_k")
    )
    if not interactive_needed:
        return args

    if not stdin_is_tty:
        if args.pages is None:
            args.pages = DEFAULT_PAGES
        if args.top_k is None:
            args.top_k = DEFAULT_TOP_K
        return args

    _show_interactive_banner()
    if not args.favorites_user:
        args.favorites_user = _prompt_non_empty("请输入收藏夹用户 ID")
    if not args.author_id:
        args.author_id = _prompt_non_empty("请输入作者 ID")
    if args.pages is None:
        args.pages = _prompt_int("请输入最大抓取页数，0 表示全量", default=DEFAULT_PAGES, minimum=0)
    if args.top_k is None:
        args.top_k = _prompt_int("请输入推荐结果 top-k", default=DEFAULT_TOP_K, minimum=1)

    _confirm_interactive_run(args)
    return args


def _validate_args(args: argparse.Namespace) -> None:
    if not args.favorites_user or not str(args.favorites_user).strip():
        raise EndToEndError("favorites-user cannot be empty.")
    if not args.author_id or not str(args.author_id).strip():
        raise EndToEndError("author-id cannot be empty.")
    if args.pages is None:
        args.pages = DEFAULT_PAGES
    if args.top_k is None:
        args.top_k = DEFAULT_TOP_K
    if int(args.pages) < 0:
        raise EndToEndError("pages must be an integer greater than or equal to 0.")
    if int(args.top_k) < 1:
        raise EndToEndError("top-k must be an integer greater than or equal to 1.")


def _require_crawler_environment(crawler_python: Path, crawler_workdir: Path) -> tuple[Path, Path, Path]:
    _check_path_exists(crawler_python, "Crawler Python")
    _check_path_exists(crawler_workdir, "Crawler workdir")

    run_py = crawler_workdir / "run.py"
    _check_path_exists(run_py, "Crawler entrypoint")

    data_dir = crawler_workdir / "data"
    cookies_path = data_dir / "cookies.json"
    if not cookies_path.exists():
        raise EndToEndError(
            "Crawler cookies not found. This end-to-end command defaults to headless mode and requires an existing "
            "login cookie at datacrawl/zhihu_crawler/data/cookies.json. First complete one manual login-enabled crawl "
            "inside datacrawl/zhihu_crawler."
        )

    return run_py, data_dir, cookies_path


def _run_subprocess(command: list[str], cwd: Path, label: str) -> subprocess.CompletedProcess[str]:
    _log(f"running {label}")
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"{label} exited with code {result.returncode}"
        raise EndToEndError(f"{label} failed: {detail}")
    return result


def _extract_json_output_paths(stdout: str, *, cwd: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    pattern = re.compile(r"([A-Za-z0-9_./-]+\.json)")
    for line in (stdout or "").splitlines():
        for match in pattern.findall(line):
            raw_path = Path(match)
            path = raw_path if raw_path.is_absolute() else (cwd / raw_path)
            normalized = path.resolve()
            if normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)
    return candidates


def _is_valid_author_content_json(path: Path) -> bool:
    name = path.name
    return (
        path.suffix.lower() == ".json"
        and "checkpoint" not in name
        and "_state" not in name
    )


def _looks_like_empty_crawl(stdout: str) -> bool:
    normalized = (stdout or "").strip()
    if not normalized:
        return False
    markers = (
        "未找到任何收藏夹",
        "未获取到任何内容",
        "收藏夹列表页访问失败",
        "成功爬取 0 条内容",
        "找到 0 个收藏夹",
    )
    return any(marker in normalized for marker in markers)


def _find_latest_json(
    directory: Path,
    pattern: str,
    *,
    start_time: float,
    exclude_substrings: tuple[str, ...] = (),
) -> Path | None:
    candidates = []
    for path in directory.glob(pattern):
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        name = path.name
        if any(token in name for token in exclude_substrings):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, path))

    fresh = [(mtime, path) for mtime, path in candidates if mtime >= start_time]
    selected_pool = fresh or candidates
    if not selected_pool:
        return None
    selected_pool.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    return selected_pool[0][1]


def _discover_favorites_output(data_dir: Path, favorites_user: str, *, start_time: float, stdout: str = "") -> Path:
    for path in _extract_json_output_paths(stdout, cwd=data_dir.parent):
        if path.exists() and path.name.startswith(f"favorites_{favorites_user}_"):
            return path

    favorites_path = _find_latest_json(
        data_dir,
        f"favorites_{favorites_user}_*.json",
        start_time=start_time,
    )
    if favorites_path is None:
        if _looks_like_empty_crawl(stdout):
            raise EndToEndError("favorites crawl finished without producing any collection data")
        raise EndToEndError("crawler output discovery failed: no favorites JSON found")
    return favorites_path


def _discover_author_outputs(
    data_dir: Path,
    author_id: str,
    *,
    start_time: float,
    stdout: str = "",
) -> tuple[Path | None, Path | None]:
    parsed_paths = _extract_json_output_paths(stdout, cwd=data_dir.parent)
    parsed_answer_candidates: list[Path] = []
    parsed_article_candidates: list[Path] = []
    for path in parsed_paths:
        if not path.exists() or author_id not in path.name or not _is_valid_author_content_json(path):
            continue
        if "_articles_" in path.name:
            parsed_article_candidates.append(path)
        elif "_answers_" in path.name:
            parsed_answer_candidates.append(path)

    def _pick_best_answer(paths: list[Path]) -> Path | None:
        if not paths:
            return None
        aggregate = [path for path in paths if path.name.endswith("_answers_aggregate.json")]
        pool = aggregate or paths
        pool.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        return pool[0]

    def _pick_latest(paths: list[Path]) -> Path | None:
        if not paths:
            return None
        paths.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        return paths[0]

    parsed_answers = _pick_best_answer(parsed_answer_candidates)
    parsed_articles = _pick_latest(parsed_article_candidates)

    if parsed_answers is not None or parsed_articles is not None:
        return parsed_answers, parsed_articles

    aggregate_path = data_dir / f"author_{author_id}_answers_aggregate.json"
    answers_path: Path | None = None
    if aggregate_path.exists():
        try:
            aggregate_mtime = aggregate_path.stat().st_mtime
        except OSError:
            aggregate_mtime = 0.0
        if aggregate_mtime >= start_time:
            answers_path = aggregate_path
    if answers_path is None and aggregate_path.exists():
        answers_path = aggregate_path

    if answers_path is None:
        answers_path = _find_latest_json(
            data_dir,
            f"author_{author_id}_*.json",
            start_time=start_time,
            exclude_substrings=("checkpoint", "_state", "_articles_", "_aggregate"),
        )

    articles_path = _find_latest_json(
        data_dir,
        f"author_{author_id}_articles_*.json",
        start_time=start_time,
        exclude_substrings=("checkpoint", "_state"),
    )
    return answers_path, articles_path


def _load_json_array(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise EndToEndError(f"Expected JSON array in crawler output: {path}")
    return payload


def _merge_candidate_outputs(
    answers_path: Path | None,
    articles_path: Path | None,
    merged_path: Path,
) -> dict:
    merged_items: list[dict] = []
    summary = {
        "answers_path": str(answers_path) if answers_path else "",
        "articles_path": str(articles_path) if articles_path else "",
        "answers_count": 0,
        "articles_count": 0,
        "merged_count": 0,
        "used_answers_aggregate": bool(answers_path and answers_path.name.endswith("_answers_aggregate.json")),
        "merged_candidates_path": str(merged_path),
    }

    if answers_path is not None:
        answer_items = _load_json_array(answers_path)
        merged_items.extend(answer_items)
        summary["answers_count"] = len(answer_items)
    if articles_path is not None:
        article_items = _load_json_array(articles_path)
        merged_items.extend(article_items)
        summary["articles_count"] = len(article_items)

    if not merged_items:
        raise EndToEndError("crawler output discovery failed: no author candidate JSON found")

    summary["merged_count"] = len(merged_items)
    _write_json(merged_path, merged_items)
    return summary


def _run_mvp(
    favorites_path: Path,
    merged_candidates_path: Path,
    *,
    top_k: int,
    output_dir: Path,
    cache_dir: Path,
) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        str(repo_root / "scripts" / "product" / "run_mvp.py"),
        "--collection",
        str(favorites_path),
        "--collection-format",
        "zhihu",
        "--candidates",
        str(merged_candidates_path),
        "--candidates-format",
        "zhihu",
        "--top-k",
        str(top_k),
        "--output-dir",
        str(output_dir),
        "--cache-dir",
        str(cache_dir),
    ]
    return _run_subprocess(command, repo_root, "recommendation MVP")


def run_workflow(args: argparse.Namespace) -> int:
    _validate_args(args)
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = Path(args.output_dir)
    cache_dir = Path(args.cache_dir)
    crawler_python = _normalize_cli_path(args.crawler_python, repo_root=repo_root, resolve_symlinks=False)
    crawler_workdir = _normalize_cli_path(args.crawler_workdir, repo_root=repo_root, resolve_symlinks=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    run_py, data_dir, cookies_path = _require_crawler_environment(crawler_python, crawler_workdir)

    favorites_started = time.time()
    favorites_command = [
        str(crawler_python),
        str(run_py),
        "--favorites",
        args.favorites_user,
        "--pages",
        "5",
        "--headless",
    ]
    favorites_result = _run_subprocess(favorites_command, crawler_workdir, "favorites crawl")
    favorites_path = _discover_favorites_output(
        data_dir,
        args.favorites_user,
        start_time=favorites_started,
        stdout=favorites_result.stdout or "",
    )

    author_started = time.time()
    author_command = [
        str(crawler_python),
        str(run_py),
        "--author",
        args.author_id,
        "--type",
        "all",
        "--pages",
        str(args.pages),
        "--headless",
    ]
    author_result = _run_subprocess(author_command, crawler_workdir, "author crawl")
    answers_path, articles_path = _discover_author_outputs(
        data_dir,
        args.author_id,
        start_time=author_started,
        stdout=author_result.stdout or "",
    )

    merged_candidates_path = output_dir / "crawler_candidates_merged.json"
    crawler_summary = _merge_candidate_outputs(answers_path, articles_path, merged_candidates_path)
    crawler_summary.update(
        {
            "favorites_path": str(favorites_path),
            "crawler_data_dir": str(data_dir),
            "cookies_path": str(cookies_path),
            "favorites_stdout": (favorites_result.stdout or "").strip(),
            "author_stdout": (author_result.stdout or "").strip(),
        }
    )

    _log("running recommendation MVP")
    mvp_result = _run_mvp(
        favorites_path,
        merged_candidates_path,
        top_k=args.top_k,
        output_dir=output_dir,
        cache_dir=cache_dir,
    )
    if mvp_result.stdout:
        print(mvp_result.stdout, end="" if mvp_result.stdout.endswith("\n") else "\n")

    crawler_run_config = {
        "favorites_command": favorites_command,
        "author_command": author_command,
        "crawler_python": str(crawler_python),
        "crawler_workdir": str(crawler_workdir),
    }
    end_to_end_run_config = {
        "favorites_user": args.favorites_user,
        "author_id": args.author_id,
        "pages": args.pages,
        "top_k": args.top_k,
        "output_dir": str(output_dir),
        "cache_dir": str(cache_dir),
        "mode": "fresh_only",
        "candidate_source": "author_all_content",
        "headless_requires_cookie": True,
    }
    _write_json(output_dir / "crawler_run_config.json", crawler_run_config)
    _write_json(output_dir / "crawler_output_summary.json", crawler_summary)
    _write_json(output_dir / "end_to_end_run_config.json", end_to_end_run_config)
    return 0


def main() -> None:
    try:
        args = _resolve_interactive_args(parse_args())
        raise SystemExit(run_workflow(args))
    except (FileNotFoundError, ValueError, EndToEndError) as exc:
        error_console.print(f"[bold red][E2E] error:[/bold red] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
