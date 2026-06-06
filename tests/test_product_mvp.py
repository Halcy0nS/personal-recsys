"""
Product MVP smoke tests.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.product import run_end_to_end
from src.utils.data_loader import load_generic_items, load_items, prepare_collection_candidates


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_data_loader_paths():
    print("\n[Test] Product MVP data loader")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        generic_path = root / "generic.json"
        zhihu_path = root / "zhihu.json"

        _write_json(
            generic_path,
            [
                {"id": "a", "title": "A", "content": "Alpha", "tags": ["ml"], "metadata": {"url": "https://a"}},
                {"id": "b", "title": "B", "content": "Beta", "tags": [], "metadata": {}},
            ],
        )
        _write_json(
            zhihu_path,
            [
                {"id": "z1", "title": "Zhihu 1", "content": "Body", "url": "https://z1", "tags": ["tag1"]},
            ],
        )

        generic_items = load_generic_items(str(generic_path))
        zhihu_items = load_items(str(zhihu_path), "zhihu")
        assert generic_items[0]["metadata"]["source"] == "generic"
        assert zhihu_items[0]["metadata"]["source"] == "zhihu"

        deduped_collection, deduped_candidates, summary = prepare_collection_candidates(
            generic_items,
            [
                {"id": "b", "title": "Dup", "content": "Dup", "tags": [], "metadata": {}},
                {"id": "c", "title": "C", "content": "Gamma", "tags": [], "metadata": {}},
                {"id": "c", "title": "C2", "content": "Gamma2", "tags": [], "metadata": {}},
            ],
        )
        assert len(deduped_collection) == 2
        assert len(deduped_candidates) == 1
        assert summary["candidate_duplicate_count"] == 1
        assert summary["candidate_overlap_removed_count"] == 1
        print("  ✓ data loading and dedupe work")


def test_generic_schema_validation():
    print("\n[Test] Product MVP generic schema validation")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        invalid_path = root / "invalid.json"
        _write_json(
            invalid_path,
            [
                {"id": "a", "title": "A", "content": "Alpha", "metadata": {}},
            ],
        )

        try:
            load_generic_items(str(invalid_path))
        except ValueError as exc:
            assert "missing required fields" in str(exc)
        else:
            raise AssertionError("Expected generic schema validation to fail")
        print("  ✓ invalid schema fails with readable error")


def test_product_cli_smoke():
    print("\n[Test] Product MVP CLI smoke")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        collection_path = root / "collection.json"
        candidates_path = root / "candidates.json"
        output_dir = root / "output"
        cache_dir = root / "cache"

        _write_json(
            collection_path,
            [
                {"id": "fav-1", "title": "Favorite A", "content": "Machine learning systems", "tags": ["ml"], "metadata": {}},
                {"id": "fav-2", "title": "Favorite B", "content": "Distributed systems analysis", "tags": ["systems"], "metadata": {}},
            ],
        )
        _write_json(
            candidates_path,
            [
                {"id": "fav-2", "title": "Overlap", "content": "Should be removed", "tags": [], "metadata": {}},
                {"id": "cand-1", "title": "Candidate 1", "content": "Machine learning article", "tags": ["ml"], "metadata": {"url": "https://cand1"}},
                {"id": "cand-2", "title": "Candidate 2", "content": "Databases and systems", "tags": ["db"], "metadata": {}},
            ],
        )

        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "product" / "run_mvp.py"),
            "--collection",
            str(collection_path),
            "--collection-format",
            "generic",
            "--candidates",
            str(candidates_path),
            "--candidates-format",
            "generic",
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(cache_dir),
            "--top-k",
            "2",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert "[MVP] loading inputs" in result.stdout
        assert "[MVP] writing artifacts" in result.stdout
        for filename in ("run_config.json", "input_summary.json", "recommendations.json", "engine_meta.json"):
            assert (output_dir / filename).exists(), filename
        recommendations = json.loads((output_dir / "recommendations.json").read_text(encoding="utf-8"))
        assert len(recommendations["recommendations"]) == 2
        summary = json.loads((output_dir / "input_summary.json").read_text(encoding="utf-8"))
        assert summary["candidate_overlap_removed_count"] == 1
        print("  ✓ CLI workflow writes artifacts")


def test_product_cli_invalid_path():
    print("\n[Test] Product MVP CLI invalid path")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "product" / "run_mvp.py"),
            "--collection",
            str(root / "missing_collection.json"),
            "--collection-format",
            "generic",
            "--candidates",
            str(root / "missing_candidates.json"),
            "--candidates-format",
            "generic",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode != 0
        assert "[MVP] error:" in result.stderr
        print("  ✓ invalid path exits non-zero")


def test_end_to_end_missing_cookie_fails():
    print("\n[Test] Product end-to-end missing cookie")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        crawler_root = root / "crawler"
        data_dir = crawler_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        run_py = crawler_root / "run.py"
        run_py.write_text("print('crawler placeholder')\n", encoding="utf-8")
        python_path = Path(sys.executable)

        args = argparse.Namespace(
            favorites_user="cjm926",
            author_id="author-x",
            pages=0,
            top_k=20,
            crawler_python=str(python_path),
            crawler_workdir=str(crawler_root),
            output_dir=str(root / "output"),
            cache_dir=str(root / "cache"),
        )
        try:
            run_end_to_end.run_workflow(args)
        except run_end_to_end.EndToEndError as exc:
            assert "cookies" in str(exc).lower()
        else:
            raise AssertionError("Expected missing cookie failure")
        print("  ✓ missing cookie fails clearly")


def test_end_to_end_output_discovery_helpers():
    print("\n[Test] Product end-to-end output discovery")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        start_time = 1.0

        favorites = data_dir / "favorites_cjm926_all_20260305_150447.json"
        answers = data_dir / "author_demo_answers_aggregate.json"
        articles = data_dir / "author_demo_articles_20260305_180331.json"
        checkpoint = data_dir / "author_demo_answers_detail_checkpoint.json"
        for path, payload in (
            (favorites, [{"id": "fav-1"}]),
            (answers, [{"id": "ans-1"}]),
            (articles, [{"id": "art-1"}]),
            (checkpoint, [{"id": "bad"}]),
        ):
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.utime(path, (start_time + 10, start_time + 10))

        found_favorites = run_end_to_end._discover_favorites_output(data_dir, "cjm926", start_time=start_time)
        found_answers, found_articles = run_end_to_end._discover_author_outputs(data_dir, "demo", start_time=start_time)
        assert found_favorites == favorites
        assert found_answers == answers
        assert found_articles == articles
        print("  ✓ discovery prefers aggregate and skips checkpoints")


def test_end_to_end_output_discovery_from_stdout():
    print("\n[Test] Product end-to-end output discovery from stdout")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        crawler_root = root / "crawler"
        data_dir = crawler_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        favorites = data_dir / "favorites_cjm926_all_20260326_120000.json"
        articles = data_dir / "author_demo_articles_20260326_120001.json"
        favorites.write_text(json.dumps([{"id": "fav-1"}], ensure_ascii=False), encoding="utf-8")
        articles.write_text(json.dumps([{"id": "art-1"}], ensure_ascii=False), encoding="utf-8")

        favorites_stdout = f"✓ JSON数据已保存: data/{favorites.name}\n"
        author_stdout = f"✓ JSON数据已保存: data/{articles.name}\n"

        found_favorites = run_end_to_end._discover_favorites_output(
            data_dir,
            "cjm926",
            start_time=9999999999.0,
            stdout=favorites_stdout,
        )
        found_answers, found_articles = run_end_to_end._discover_author_outputs(
            data_dir,
            "demo",
            start_time=9999999999.0,
            stdout=author_stdout,
        )
        assert found_favorites == favorites.resolve()
        assert found_answers is None
        assert found_articles == articles.resolve()
        print("  ✓ discovery can use crawler stdout paths directly")


def test_end_to_end_output_discovery_ignores_checkpoint_from_stdout():
    print("\n[Test] Product end-to-end stdout ignores checkpoint/state")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        crawler_root = root / "crawler"
        data_dir = crawler_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        checkpoint = data_dir / "author_demo_answers_index_checkpoint.json"
        aggregate = data_dir / "author_demo_answers_aggregate.json"
        state = data_dir / "author_demo_answers_aggregate_state.json"
        article = data_dir / "author_demo_articles_20260326_120001.json"

        for path in (checkpoint, aggregate, state, article):
            path.write_text(json.dumps([{"id": path.stem}], ensure_ascii=False), encoding="utf-8")
            os.utime(path, None)

        stdout = "\n".join(
            [
                f"answers: data/{checkpoint.name}",
                f"answers: data/{aggregate.name}",
                f"answers: data/{state.name}",
                f"articles: data/{article.name}",
            ]
        )

        found_answers, found_articles = run_end_to_end._discover_author_outputs(
            data_dir,
            "demo",
            start_time=9999999999.0,
            stdout=stdout,
        )
        assert found_answers == aggregate.resolve()
        assert found_articles == article.resolve()
        print("  ✓ checkpoint/state stdout entries are ignored")


def test_end_to_end_empty_favorites_crawl_reports_clear_error():
    print("\n[Test] Product end-to-end empty favorites crawl error")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            run_end_to_end._discover_favorites_output(
                data_dir,
                "cjm926",
                start_time=time.time(),
                stdout="⚠ 未找到任何收藏夹\n",
            )
        except run_end_to_end.EndToEndError as exc:
            assert "without producing any collection data" in str(exc)
        else:
            raise AssertionError("Expected clear empty favorites crawl error")
        print("  ✓ empty favorites crawl reports a clearer error")


def test_end_to_end_cli_smoke():
    print("\n[Test] Product end-to-end CLI smoke")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        crawler_root = root / "crawler"
        data_dir = crawler_root / "data"
        output_dir = root / "output"
        cache_dir = root / "cache"
        data_dir.mkdir(parents=True, exist_ok=True)
        (crawler_root / "run.py").write_text("print('crawler placeholder')\n", encoding="utf-8")
        (data_dir / "cookies.json").write_text("[]\n", encoding="utf-8")

        real_subprocess_run = subprocess.run

        def fake_subprocess_run(command, cwd=None, capture_output=False, text=False, check=False):
            command = [str(part) for part in command]
            if command[-1].endswith("run.py") or (len(command) >= 2 and command[1].endswith("run.py")):
                if "--favorites" in command:
                    favorites_path = data_dir / "favorites_cjm926_auto.json"
                    favorites_payload = [
                        {"id": "fav-1", "title": "Fav 1", "content": "A", "tags": ["ml"], "metadata": {}},
                        {"id": "fav-2", "title": "Fav 2", "content": "B", "tags": ["systems"], "metadata": {}},
                    ]
                    favorites_path.write_text(json.dumps(favorites_payload, ensure_ascii=False), encoding="utf-8")
                    os.utime(favorites_path, None)
                    return subprocess.CompletedProcess(command, 0, stdout="favorites ok\n", stderr="")
                answers_path = data_dir / "author_demo_answers_aggregate.json"
                articles_path = data_dir / "author_demo_articles_latest.json"
                answers_payload = [
                    {"id": "ans-1", "title": "Ans 1", "content": "A", "url": "https://ans1", "tags": ["ml"], "metadata": {}},
                ]
                articles_payload = [
                    {"id": "art-1", "title": "Art 1", "content": "B", "url": "https://art1", "tags": ["db"], "metadata": {}},
                ]
                answers_path.write_text(json.dumps(answers_payload, ensure_ascii=False), encoding="utf-8")
                articles_path.write_text(json.dumps(articles_payload, ensure_ascii=False), encoding="utf-8")
                os.utime(answers_path, None)
                os.utime(articles_path, None)
                return subprocess.CompletedProcess(command, 0, stdout="author ok\n", stderr="")
            if "run_mvp.py" in command[1]:
                result = real_subprocess_run(
                    [
                        sys.executable,
                        command[1],
                        *command[2:],
                    ],
                    capture_output=capture_output,
                    text=text,
                    check=check,
                )
                return result
            return real_subprocess_run(command, cwd=cwd, capture_output=capture_output, text=text, check=check)

        original_subprocess_run = run_end_to_end.subprocess.run
        run_end_to_end.subprocess.run = fake_subprocess_run
        try:
            args = argparse.Namespace(
                favorites_user="cjm926",
                author_id="demo",
                pages=0,
                top_k=2,
                crawler_python=str(Path(sys.executable)),
                crawler_workdir=str(crawler_root),
                output_dir=str(output_dir),
                cache_dir=str(cache_dir),
            )
            exit_code = run_end_to_end.run_workflow(args)
            assert exit_code == 0
        finally:
            run_end_to_end.subprocess.run = original_subprocess_run

        for filename in (
            "crawler_run_config.json",
            "crawler_output_summary.json",
            "end_to_end_run_config.json",
            "run_config.json",
            "input_summary.json",
            "recommendations.json",
            "engine_meta.json",
        ):
            assert (output_dir / filename).exists(), filename
        summary = json.loads((output_dir / "crawler_output_summary.json").read_text(encoding="utf-8"))
        assert summary["answers_count"] == 1
        assert summary["articles_count"] == 1
        print("  ✓ end-to-end workflow writes crawler and recommendation artifacts")


def test_end_to_end_interactive_prompt_completion():
    print("\n[Test] Product end-to-end interactive prompt completion")
    answers = iter(["cjm926", "demo", "", "", ""])
    original_input = run_end_to_end.console.input
    original_isatty = sys.stdin.isatty
    try:
        sys.stdin.isatty = lambda: True
        run_end_to_end.console.input = lambda _prompt="": next(answers)
        args = argparse.Namespace(
            favorites_user=None,
            author_id=None,
            pages=None,
            top_k=None,
            crawler_python=run_end_to_end.DEFAULT_CRAWLER_PYTHON,
            crawler_workdir=run_end_to_end.DEFAULT_CRAWLER_WORKDIR,
            output_dir=run_end_to_end.DEFAULT_OUTPUT_DIR,
            cache_dir=run_end_to_end.DEFAULT_CACHE_DIR,
        )
        resolved = run_end_to_end._resolve_interactive_args(args)
    finally:
        sys.stdin.isatty = original_isatty
        run_end_to_end.console.input = original_input

    assert resolved.favorites_user == "cjm926"
    assert resolved.author_id == "demo"
    assert resolved.pages == 0
    assert resolved.top_k == 20
    print("  ✓ missing args can be completed interactively")


def test_end_to_end_interactive_cancel():
    print("\n[Test] Product end-to-end interactive cancel")
    answers = iter(["cjm926", "demo", "", "", "n"])
    original_input = run_end_to_end.console.input
    original_isatty = sys.stdin.isatty
    try:
        sys.stdin.isatty = lambda: True
        run_end_to_end.console.input = lambda _prompt="": next(answers)
        args = argparse.Namespace(
            favorites_user=None,
            author_id=None,
            pages=None,
            top_k=None,
            crawler_python=run_end_to_end.DEFAULT_CRAWLER_PYTHON,
            crawler_workdir=run_end_to_end.DEFAULT_CRAWLER_WORKDIR,
            output_dir=run_end_to_end.DEFAULT_OUTPUT_DIR,
            cache_dir=run_end_to_end.DEFAULT_CACHE_DIR,
        )
        try:
            run_end_to_end._resolve_interactive_args(args)
        except run_end_to_end.EndToEndError as exc:
            assert "cancelled" in str(exc).lower()
        else:
            raise AssertionError("Expected interactive cancellation")
    finally:
        sys.stdin.isatty = original_isatty
        run_end_to_end.console.input = original_input
    print("  ✓ interactive cancel exits cleanly")


def test_end_to_end_non_tty_uses_defaults_without_prompt():
    print("\n[Test] Product end-to-end non-tty defaults")
    original_input = run_end_to_end.console.input
    original_isatty = sys.stdin.isatty
    try:
        sys.stdin.isatty = lambda: False
        run_end_to_end.console.input = lambda _prompt="": (_ for _ in ()).throw(AssertionError("Prompt should not be called"))
        args = argparse.Namespace(
            favorites_user="cjm926",
            author_id="demo",
            pages=None,
            top_k=None,
            crawler_python=run_end_to_end.DEFAULT_CRAWLER_PYTHON,
            crawler_workdir=run_end_to_end.DEFAULT_CRAWLER_WORKDIR,
            output_dir=run_end_to_end.DEFAULT_OUTPUT_DIR,
            cache_dir=run_end_to_end.DEFAULT_CACHE_DIR,
        )
        resolved = run_end_to_end._resolve_interactive_args(args)
    finally:
        sys.stdin.isatty = original_isatty
        run_end_to_end.console.input = original_input

    assert resolved.pages == 0
    assert resolved.top_k == 20
    print("  ✓ non-tty mode falls back to defaults")


def test_end_to_end_invalid_numeric_args():
    print("\n[Test] Product end-to-end invalid numeric args")
    bad_pages = argparse.Namespace(
        favorites_user="cjm926",
        author_id="demo",
        pages=-1,
        top_k=20,
        crawler_python=run_end_to_end.DEFAULT_CRAWLER_PYTHON,
        crawler_workdir=run_end_to_end.DEFAULT_CRAWLER_WORKDIR,
        output_dir=run_end_to_end.DEFAULT_OUTPUT_DIR,
        cache_dir=run_end_to_end.DEFAULT_CACHE_DIR,
    )
    try:
        run_end_to_end._validate_args(bad_pages)
    except run_end_to_end.EndToEndError as exc:
        assert "pages" in str(exc).lower()
    else:
        raise AssertionError("Expected pages validation error")

    bad_top_k = argparse.Namespace(
        favorites_user="cjm926",
        author_id="demo",
        pages=0,
        top_k=0,
        crawler_python=run_end_to_end.DEFAULT_CRAWLER_PYTHON,
        crawler_workdir=run_end_to_end.DEFAULT_CRAWLER_WORKDIR,
        output_dir=run_end_to_end.DEFAULT_OUTPUT_DIR,
        cache_dir=run_end_to_end.DEFAULT_CACHE_DIR,
    )
    try:
        run_end_to_end._validate_args(bad_top_k)
    except run_end_to_end.EndToEndError as exc:
        assert "top-k" in str(exc).lower()
    else:
        raise AssertionError("Expected top-k validation error")
    print("  ✓ numeric validation rejects bad values")


def run_all_tests():
    test_data_loader_paths()
    test_generic_schema_validation()
    test_product_cli_smoke()
    test_product_cli_invalid_path()
    test_end_to_end_missing_cookie_fails()
    test_end_to_end_output_discovery_helpers()
    test_end_to_end_output_discovery_from_stdout()
    test_end_to_end_output_discovery_ignores_checkpoint_from_stdout()
    test_end_to_end_empty_favorites_crawl_reports_clear_error()
    test_end_to_end_cli_smoke()
    test_end_to_end_interactive_prompt_completion()
    test_end_to_end_interactive_cancel()
    test_end_to_end_non_tty_uses_defaults_without_prompt()
    test_end_to_end_invalid_numeric_args()
    print("\nProduct MVP tests completed.")


if __name__ == "__main__":
    run_all_tests()
