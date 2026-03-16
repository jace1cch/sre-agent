"""Shared models for hybrid operational retrieval."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class RetrievalChunk:
    """One retrievable unit from code or incident history."""

    chunk_id: str
    corpus: str
    content: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalMatch:
    """One scored retrieval result."""

    chunk: RetrievalChunk
    score: float
    strategy: str


@dataclass(slots=True)
class GoldenExample:
    """One hand-labelled retrieval evaluation example."""

    query: str
    expected_files: list[str]
    expected_keywords: list[str]
    description: str
