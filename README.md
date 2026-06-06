# Personal RecSys

[简体中文](README_ZH.md)

Personal RecSys is a local, explainable content recommendation core written in Python. The runnable recommendation path in this repository lives under `src/`: it builds a user profile from a collection, scores candidates with vector similarity and tag rules, and produces weighted ranking results with per-stage timing.

## Scope

Implemented in this repository:

- A public recommendation API via `src.engine.PersonalRecSys`
- Implicit profiling with a multi-vector `VectorCloud`
- Optional explicit profiling with `UserExplicitProfile` and `ProfileExtractor`
- Retrieval with item-to-item similarity and rule-based tag matching
- Ranking with normalized weighted score fusion and preset strategies
- Optional LM Studio helpers for embeddings and LLM calls
- Scripted demos in `example_usage.py` and `run_real_data.py` (canonical entrypoints now live under `scripts/demo/`, while the top-level files remain compatibility wrappers)

Not implemented in the current codebase:

- Desktop GUI code
- Packaging or installer flows
- Runtime service orchestration outside the Python process
- Automatic crawler integration into the main engine path

Those boundaries are based on the current source tree and imports, not on historical docs.

## Architecture

The main runtime flow is:

1. `src.engine.PersonalRecSys` owns engine state and exposes the public API.
2. `src.pipeline.orchestrator.PipelineOrchestrator` executes the staged pipeline.
3. `src.services.*` adapts profile building, retrieval aggregation, ranking, and optional reranking.
4. `src.profiling`, `src.retrieval`, and `src.ranking` contain the domain logic.
5. `src.contracts` defines shared config, interfaces, and stage-level data structures.
6. `src.utils` provides embedding backends, LM Studio client helpers, and data loaders.

Current stage order inside `PipelineOrchestrator`:

1. Build `ProfileContext`
2. Retrieve scores with `RetrievalManager`
3. Coarse-rank all candidates with `DefaultRanker`
4. Optionally rerank with `LLMReranker`
5. Run final ranking and return `RecommendationResult`

## Package Map

| Package | Responsibility | Main classes / functions |
| --- | --- | --- |
| `src.engine` | Public API, engine state, cache save/load | `PersonalRecSys`, `CandidateItem`, `RecommendationResult` |
| `src.pipeline` | Stage orchestration | `PipelineOrchestrator` |
| `src.contracts` | Config, abstract interfaces, stage contracts | `PipelineConfig`, `BaseProfileBuilder`, `BaseRetriever`, `BaseRanker`, `ProfileContext` |
| `src.services` | Concrete service adapters | `DefaultProfileBuilder`, `RetrievalManager`, `DefaultRanker`, `LLMReranker` |
| `src.profiling` | User profile construction and persistence | `VectorCloud`, `UserExplicitProfile`, `ProfileExtractor` |
| `src.retrieval` | Candidate scoring logic | `I2IMatcher`, `BatchI2IMatcher`, `TagMatcher` |
| `src.ranking` | Score normalization and fusion | `ScoreComponent`, `WeightedScorer`, `ConfigurableScorer`, `RankedItem` |
| `src.utils` | Embeddings, LM Studio client, data loading helpers | `get_embedder`, `LMStudioLLMClient`, `load_zhihu_items`, `compute_popularity` |

## Public API

`PersonalRecSys` is the main entry point.

Core methods:

- `build_profile_from_collection(collection_items, llm_client=None, max_items=50)`
- `add_candidates(items)`
- `embed_candidates(batch_size=32)`
- `recommend(top_k=20, preset="balanced", custom_weights=None, min_score=None)`
- `save(path)` / `load(path, embedder=None)`

Main runtime data structures:

- `CandidateItem`
- `RecommendationResult`
- `RankedItem`

Minimal usage example:

```python
from src.engine import PersonalRecSys, CandidateItem
from src.utils.embeddings import get_embedder

recsys = PersonalRecSys(
    embedder=get_embedder("mock", dim=128),
    embedding_dim=128,
)

recsys.build_profile_from_collection([
    {"title": "Example", "content": "Profile source text"}
])

recsys.add_candidates([
    CandidateItem(item_id="a", title="Candidate A", content="...", tags=["tag1"])
])
recsys.embed_candidates()
results = recsys.recommend(top_k=5, preset="balanced")
```

## Verified Runtime Behavior

- `recommend()` requires both a candidate pool and an implicit profile; otherwise it raises `ValueError`.
- `build_profile_from_collection(..., llm_client=None)` builds only the implicit profile.
- `TagRetriever` falls back to a uniform tag score of `0.5` when no explicit profile exists.
- Popularity only comes from `candidate.metadata["popularity"]` in the default pipeline.
- `ScoreComponent.RECENCY` and `ScoreComponent.DIVERSITY` exist in the enum but are not produced by the default engine flow.
- `save()` and `load()` persist profile artifacts and `meta.json`, but do not restore the candidate pool.
- `embed_candidates()` embeds `title + content` text truncated to 2000 characters.
- `filter_count` is currently derived from candidates whose tag score equals `0.0`; it is not a dedicated “hard-filter rejection” counter.

## Configuration Notes

`PipelineConfig` centralizes runtime options, but not every field is wired end-to-end in the current call path.

- `top_k`, `preset`, and `custom_weights` are used as orchestrator defaults.
- `embedder_type` and related embedder fields do not automatically instantiate an embedder; `PersonalRecSys` still uses the explicit `embedder` argument, or falls back to the mock embedder.
- `min_score` exists on `PipelineConfig`, but the current `recommend()` path does not automatically fall back to `config.min_score` when the call argument is omitted.

## Embedding and LLM Backends

Available embedders in `src/utils/embeddings.py`:

- `mock`
- `openai`
- `local`
- `lmstudio`

Code-verified dependency notes:

- `requirements.txt` currently declares only `numpy`.
- `OpenAIEmbedder` requires the `openai` package.
- `LocalEmbedder` requires `sentence-transformers`.
- `VectorCloud.get_clusters()` imports `sklearn.cluster.KMeans` lazily, but `scikit-learn` is not listed in `requirements.txt`.
- LM Studio integrations use stdlib `urllib`, but require a local LM Studio server exposing OpenAI-compatible endpoints.

## Optional Reranking

`src/services/reranker.py` implements `LLMReranker`, and `PipelineOrchestrator` supports `set_reranker(...)`.

Important limitation:

- `PersonalRecSys` does not expose a dedicated public helper for enabling reranking.
- The default examples do not wire the reranker into the high-level engine flow.
- `docs/reranker_prompts.py` and `docs/reranker_prompts_v2.py` are reference materials; the active prompt builder lives inside `src/services/reranker.py`.

## Repository Layout

```text
personal-recsys/
├── src/                    # Runtime recommendation engine
├── experiments/            # Experiment and evaluation implementations
├── scripts/                # Canonical script entrypoints
├── tests/                  # Script-style validation
├── research/               # Research notes
├── docs/                   # Supplementary docs and prompt references
├── data/                   # Local data/cache directory
├── datacrawl/              # Separate data collection workspace
├── example_usage.py        # Top-level compatibility wrapper
├── run_real_data.py        # Top-level compatibility wrapper
└── requirements.txt
```

`docs/` is useful context, but it is not imported by the runtime engine. `scripts/` is now the canonical entrypoint directory; the top-level `run_*.py` files and `example_usage.py` remain as compatibility wrappers.

## Local MVP CLI

The repository now also includes a no-LLM local MVP CLI for the minimum single-user recommendation workflow:

```bash
python3 scripts/product/run_mvp.py \
  --collection path/to/collection.json \
  --collection-format zhihu \
  --candidates path/to/candidates.json \
  --candidates-format zhihu
```

First-version characteristics:

- single-command workflow
- implicit profile only
- no explicit profile and no reranker
- supports `zhihu` and `generic` JSON inputs
- writes `run_config.json`, `input_summary.json`, `recommendations.json`, and `engine_meta.json`

The first-version `generic` JSON format requires each item to include:

- `id`
- `title`
- `content`
- `tags`
- `metadata`

## End-to-End Crawl To Recommendation

The repository now also includes an orchestration entrypoint that chains the existing Zhihu crawler and the local recommendation MVP into one command:

```bash
python3 scripts/product/run_end_to_end.py \
  --favorites-user cjm926 \
  --author-id some-author-id
```

If you omit `--favorites-user`, `--author-id`, `--pages`, or `--top-k`, the same entrypoint now falls back to an interactive product prompt and asks for the missing values before running.

First-version constraints:

- directly reuses `datacrawl/zhihu_crawler`
- always performs a fresh crawl
- uses author all-content (answers + articles) as the default candidate pool
- runs headless by default, but requires an existing `datacrawl/zhihu_crawler/data/cookies.json`
- first-time login is not handled by this command

This command also writes:

- `crawler_run_config.json`
- `crawler_output_summary.json`
- `end_to_end_run_config.json`

Interactive example:

```bash
python3 scripts/product/run_end_to_end.py
```

## Quick Start

Install the current minimum dependency set:

```bash
python3 -m pip install -r requirements.txt
```

Run the lightweight demo:

```bash
python3 scripts/demo/example_usage.py
```

Run the script-based checks:

```bash
python3 tests/test_basic.py
```

## Real-Data Demo

`scripts/demo/run_real_data.py` demonstrates the engine with:

- Zhihu-style JSON inputs loaded through `src/utils/data_loader.py`
- LM Studio for embeddings and explicit-profile extraction
- Popularity derived from `voteup_count` and `comment_count`

The script currently expects:

- a local LM Studio server at `http://localhost:1234/v1`
- JSON files under `datacrawl/zhihu_crawler/data`

Run it with:

```bash
python3 scripts/demo/run_real_data.py
```

## Simulator Experiment

The repository also includes an offline `user simulator` experiment for comparing `fulltext` vs `adaptive compressed` article views with pairwise Glicko2 ranking. It writes `simulator ranking` artifacts only and should not be treated as human ground truth.

Important caveat: the `compressed` lane evaluates simulator preference over structured evidence, not the full article as-written. See the representation caveats in [docs/simulator_glicko_experiment.md](docs/simulator_glicko_experiment.md).

See [docs/simulator_glicko_experiment.md](docs/simulator_glicko_experiment.md) and run:

```bash
python3 scripts/experiments/run_simulator_glicko_experiment.py
```

## Product Roadmap

The repository now also has a long-term product roadmap for evolving the current engine into a **local, single-user, interactive recommendation product**.

This roadmap is intentionally different from runtime docs:

- `README.md` describes current code facts
- `docs/PROJECT_STATUS.md` describes current status
- [docs/product_roadmap.md](docs/product_roadmap.md) describes the intended build sequence and product priorities

The current priority order in that roadmap is:

1. strengthen recommendation quality in the main engine
2. productize a general rerank slot
3. standardize evaluation as product R&D infrastructure
4. add a local interaction loop
5. harden the product experience

## Persistence

When `cache_dir` is configured, the engine may read and write:

- `vector_cloud.json`
- `explicit_profile.json`

`save(path)` also writes:

- `meta.json`

`load(path)` restores the profile state and embedding dimension, but you must add candidates again before calling `recommend()`.

## Development Notes

- `tests/test_basic.py` is a script with assertions and stdout logging, not a formal pytest suite.
- `example_usage.py` manually injects an explicit profile after building the implicit one; this is a demo choice, not an automatic engine behavior.
- `RecommendRequest` and `RecommendResponse` exist in `src/contracts/types.py`, but the public `PersonalRecSys.recommend()` API currently uses direct parameters and returns `RecommendationResult`.

## License Status

No `LICENSE` file is present in the repository root.

## Companion Tools (Ecosystem)

This project is the **Recommendation Engine (Right Brain)** of the Pasika architecture. It is designed to be loosely coupled with a note-generation factory (Left Brain) via standard Markdown files. 

We highly recommend using [llmwiki](https://github.com/lucasastorian/llmwiki) by lucasastorian as your knowledge-base generator. `personal-recsys` reads the markdown files produced by `llmwiki` to construct your implicit user profile (Vector Cloud). Please note that `personal-recsys` is completely independent and does not require `llmwiki` to run, as long as you provide a folder of Markdown notes.
