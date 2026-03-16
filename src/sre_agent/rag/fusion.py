"""Fusion helpers for hybrid retrieval."""

from sre_agent.rag.models import RetrievalMatch


def rrf_merge(
    exact_results: list[RetrievalMatch],
    vector_results: list[RetrievalMatch],
    *,
    exact_weight: float,
    top_k: int,
    k: int = 60,
) -> list[RetrievalMatch]:
    """Merge exact and vector results with reciprocal rank fusion."""

    scores: dict[str, float] = {}
    matches: dict[str, RetrievalMatch] = {}

    for rank, match in enumerate(exact_results):
        scores[match.chunk.chunk_id] = scores.get(match.chunk.chunk_id, 0.0) + exact_weight / (k + rank + 1)
        matches[match.chunk.chunk_id] = match

    vector_weight = 1.0 - exact_weight
    for rank, match in enumerate(vector_results):
        scores[match.chunk.chunk_id] = scores.get(match.chunk.chunk_id, 0.0) + vector_weight / (k + rank + 1)
        if match.chunk.chunk_id not in matches:
            matches[match.chunk.chunk_id] = match

    ordered_ids = sorted(scores, key=scores.get, reverse=True)
    merged: list[RetrievalMatch] = []
    for chunk_id in ordered_ids[:top_k]:
        base = matches[chunk_id]
        merged.append(
            RetrievalMatch(
                chunk=base.chunk,
                score=scores[chunk_id],
                strategy="hybrid",
            )
        )
    return merged
