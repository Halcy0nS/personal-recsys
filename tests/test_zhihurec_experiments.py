"""
ZhihuRec experiment smoke tests.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from experiments.zhihurec.baseline_mean_pool import MeanPoolBaselineConfig, run_mean_pool_experiment
from experiments.zhihurec.data import ZhihuRecSplitConfig, load_split_bundle
from experiments.zhihurec.metrics import compute_topk_metrics
from experiments.zhihurec.rerank_mlp import TwoStageRerankConfig, run_two_stage_experiment
from experiments.zhihurec.sasrec import SASRecConfig, torch as zh_torch, run_sasrec_experiment


def _write(path: Path, lines) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_answer_row(answer_id: int, token_ids: list[int], topic_ids: list[int], likes: int) -> str:
    fields = [
        str(answer_id),
        str(answer_id % 3),
        "0",
        str(answer_id % 2),
        "0",
        "0",
        str(1000 + answer_id),
        "0",
        "0",
        str(1 + answer_id),
        str(likes),
        str(2 + answer_id),
        str(3 + answer_id),
        "0",
        "0",
        "0",
        " ".join(str(token) for token in token_ids),
        " ".join(str(topic) for topic in topic_ids),
    ]
    return ",".join(fields)


def _build_tiny_dataset(root: Path) -> Path:
    data_root = root / "zhihurec_1m_tiny"
    data_root.mkdir(parents=True, exist_ok=True)
    _write(
        data_root / "inter_impression.csv",
        [
            "0,0,100,101",
            "0,1,110,111",
            "0,2,120,0",
            "0,2,130,131",
            "0,3,140,0",
            "0,1,150,151",
            "0,0,160,161",
            "1,1,170,171",
            "1,0,180,181",
            "1,2,190,0",
            "1,2,200,201",
            "1,3,210,0",
            "1,1,220,221",
            "1,0,230,231",
        ],
    )
    _write(data_root / "inter_query.csv", ["0,0 1,90", "1,2 3,95"])
    _write(data_root / "info_user.csv", ["0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0", "1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"])
    _write(
        data_root / "info_answer.csv",
        [
            _make_answer_row(0, [0, 1], [0], 10),
            _make_answer_row(1, [1, 2], [1], 20),
            _make_answer_row(2, [2, 3], [0, 1], 5),
            _make_answer_row(3, [3, 4], [2], 3),
        ],
    )
    _write(data_root / "info_question.csv", ["0,100,1,1,1,1,0 1,0", "1,100,1,1,1,1,1 2,1", "2,100,1,1,1,1,2 3,2"])
    _write(data_root / "info_author.csv", ["0,0,1,0", "1,0,1,0"])
    _write(data_root / "info_topic.csv", ["0", "1", "2"])
    _write(
        data_root / "info_token.csv",
        [
            "0,1 0 0 0",
            "1,0 1 0 0",
            "2,0 0 1 0",
            "3,0 0 0 1",
            "4,1 1 0 0",
        ],
    )
    return data_root


def test_split_bundle_and_metrics():
    print("\n[Test] ZhihuRec split bundle and metrics")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data_root = _build_tiny_dataset(root)
        output_root = root / "outputs"

        bundle = load_split_bundle(
            ZhihuRecSplitConfig(
                data_root=str(data_root),
                output_root=str(output_root),
            ),
            use_cached_split=False,
        )
        assert bundle.dataset.file_line_counts["inter_impression.csv"] == 14
        assert bundle.manifest["materialized_samples"]["train"] > 0
        assert bundle.manifest["materialized_samples"]["val"] > 0
        assert bundle.manifest["materialized_samples"]["test"] > 0
        assert all(sample.history_answer_ids for sample in bundle.train_samples)
        assert all(sample.target_answer_id not in sample.hard_negative_ids for sample in bundle.train_samples)
        assert all(
            sample.click_timestamp > 0 and sample.impression_timestamp <= sample.click_timestamp
            for sample in bundle.train_samples + bundle.val_samples + bundle.test_samples
        )

        cached_small = load_split_bundle(
            ZhihuRecSplitConfig(
                data_root=str(data_root),
                output_root=str(output_root),
                max_samples_per_split=1,
            ),
            use_cached_split=False,
        )
        cached_large = load_split_bundle(
            ZhihuRecSplitConfig(
                data_root=str(data_root),
                output_root=str(output_root),
                max_samples_per_split=2,
            ),
            use_cached_split=True,
        )
        assert cached_small.manifest["config"]["max_samples_per_split"] == 1
        assert cached_large.manifest["config"]["max_samples_per_split"] == 2
        assert len(cached_large.train_samples) > len(cached_small.train_samples)

        metrics = compute_topk_metrics(
            [
                {"target_answer_id": 2, "ranked_item_ids": [2, 1, 0]},
                {"target_answer_id": 3, "ranked_item_ids": [1, 0, 3]},
            ],
            k=2,
        )
        assert metrics.recall_at_10 == 0.5
        assert metrics.ndcg_at_10 > 0
        print("  ✓ split and metric helpers work")


def test_mean_pool_experiment_smoke():
    print("\n[Test] ZhihuRec mean-pool smoke")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data_root = _build_tiny_dataset(root)
        output_root = root / "outputs"
        split_config = ZhihuRecSplitConfig(data_root=str(data_root), output_root=str(output_root))
        bundle = load_split_bundle(split_config, use_cached_split=False)
        metrics = run_mean_pool_experiment(
            bundle,
            MeanPoolBaselineConfig(
                split_config=split_config.to_dict(),
                output_root=str(output_root),
                ranking_k=3,
            ),
        )
        assert "exp0_popularity" in metrics
        assert "exp1_mean_pool" in metrics
        assert (output_root / "exp1_mean_pool" / "metrics.json").exists()
        print("  ✓ mean-pool experiment writes artifacts")


def test_sasrec_and_two_stage_smoke():
    print("\n[Test] ZhihuRec SASRec/two-stage smoke")
    if zh_torch is None:
        print("  - skipped: torch is not installed")
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data_root = _build_tiny_dataset(root)
        output_root = root / "outputs"
        split_config = ZhihuRecSplitConfig(data_root=str(data_root), output_root=str(output_root))
        bundle = load_split_bundle(split_config, use_cached_split=False)

        sasrec_result = run_sasrec_experiment(
            bundle,
            SASRecConfig(
                output_root=str(output_root),
                hidden_dim=16,
                epochs=1,
                batch_size=2,
                eval_batch_size=2,
                ranking_k=3,
            ),
        )
        assert (output_root / "exp2_sasrec" / "metrics.json").exists()
        assert "metrics" in sasrec_result

        rerank_result = run_two_stage_experiment(
            bundle,
            MeanPoolBaselineConfig(
                split_config=split_config.to_dict(),
                output_root=str(output_root),
                ranking_k=3,
            ),
            SASRecConfig(
                output_root=str(output_root),
                hidden_dim=16,
                epochs=1,
                batch_size=2,
                eval_batch_size=2,
                ranking_k=3,
            ),
            TwoStageRerankConfig(
                output_root=str(output_root),
                hidden_dim=16,
                epochs=1,
                batch_size=4,
                ranking_k=3,
            ),
        )
        assert (output_root / "exp3_two_stage" / "metrics.json").exists()
        assert "metrics" in rerank_result
        print("  ✓ SASRec and two-stage experiments write artifacts")


def run_all_tests():
    test_split_bundle_and_metrics()
    test_mean_pool_experiment_smoke()
    test_sasrec_and_two_stage_smoke()
    print("\nZhihuRec experiment tests completed.")


if __name__ == "__main__":
    run_all_tests()
