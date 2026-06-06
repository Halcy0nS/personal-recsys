"""Compatibility exports for experiment modules."""

from importlib import import_module


_EXPORTS = {
    "RecommendationComparator": "experiments.comparator",
    "PairwiseDecision": "experiments.pairwise",
    "PairwiseEvaluationSession": "experiments.pairwise",
    "LLMPairwiseExperiment": "experiments.llm_pairwise",
    "OrderInstabilityAttributionExperiment": "experiments.order_instability_attribution",
    "CandidateAwareRAGReranker": "experiments.rag_rerank",
    "ChunkIndexStore": "experiments.rag_rerank",
    "RerankerStabilityExperiment": "experiments.reranker_stability",
    "SimulatorArticle": "experiments.simulator_glicko",
    "AdaptiveCompressionRecord": "experiments.simulator_glicko",
    "PairwiseExperimentResult": "experiments.simulator_glicko",
    "SimulatorUserProfile": "experiments.simulator_glicko",
    "SimulatorExperimentConfig": "experiments.simulator_glicko",
    "SimulatorGlickoExperiment": "experiments.simulator_glicko",
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    return getattr(module, name)
