"""Exact retrieval helpers for operational lookups."""

from pathlib import Path
import re

from sre_agent.rag.chunking import chunk_code_file, find_chunk_for_line
from sre_agent.rag.models import RetrievalChunk, RetrievalMatch
from sre_agent.utils import run_command

_ALLOWED_GLOBS = ["*.java", "*.kt", "*.groovy", "*.xml", "*.yml", "*.yaml", "*.properties", "*.py"]
_STACK_TRACE_PATTERN = re.compile(r"at\s+([\w.$]+)\.([\w$]+)\(")
_FILE_REFERENCE_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9_]+)\.(java|kt|groovy|py)(?::\d+)?\b")
_CLASS_NAME_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9_]+)\b")
_SYMBOL_CHARS_PATTERN = re.compile(r"[\w.$]{3,}")
_PREFERRED_CLASS_SUFFIXES = (
    "Service",
    "Controller",
    "Engine",
    "Util",
    "Executor",
    "ErrorCode",
    "Mapper",
    "Configuration",
    "Application",
    "Entity",
)


def extract_symbol(query: str) -> str:
    """Extract the highest-value symbol from an operational query."""

    stack_trace_match = _STACK_TRACE_PATTERN.search(query)
    if stack_trace_match is not None:
        return stack_trace_match.group(2)

    file_reference_match = _FILE_REFERENCE_PATTERN.search(query)
    if file_reference_match is not None:
        return file_reference_match.group(1)

    class_candidates = _CLASS_NAME_PATTERN.findall(query)
    preferred_class = _preferred_class_candidate(class_candidates)
    if preferred_class is not None:
        return preferred_class

    symbol_matches = _SYMBOL_CHARS_PATTERN.findall(query)
    if symbol_matches:
        return max(symbol_matches, key=len)
    return query.strip()


def exact_code_search(
    query: str,
    codebase_path: Path,
    *,
    top_k: int,
    context_lines: int,
) -> list[RetrievalMatch]:
    """Run an exact symbol-first search against the codebase."""

    symbol = extract_symbol(query)
    queries = [symbol]
    if query.strip() and query.strip() != symbol:
        queries.append(query.strip())

    results: list[RetrievalMatch] = []
    seen_chunk_ids: set[str] = set()
    for match in _direct_file_matches(codebase_path, symbol, top_k=top_k):
        results.append(match)
        seen_chunk_ids.add(match.chunk.chunk_id)
        if len(results) >= top_k:
            return results

    for search_term in queries:
        if not search_term:
            continue
        for match in _run_ripgrep(codebase_path, search_term, top_k=top_k * 2):
            chunk = _chunk_from_match(
                match["file_path"],
                match["line_number"],
                context_lines=context_lines,
            )
            if chunk is None or chunk.chunk_id in seen_chunk_ids:
                continue
            results.append(
                RetrievalMatch(
                    chunk=chunk,
                    score=1.0 / (len(results) + 1),
                    strategy="exact",
                )
            )
            seen_chunk_ids.add(chunk.chunk_id)
            if len(results) >= top_k:
                return results
    return results


def exact_text_search(
    query: str,
    chunks: list[RetrievalChunk],
    *,
    top_k: int,
) -> list[RetrievalMatch]:
    """Run a lightweight exact search across chunk text."""

    terms = _candidate_terms(query)
    scored: list[RetrievalMatch] = []
    for chunk in chunks:
        haystack = chunk.content.lower()
        score = 0.0
        for term in terms:
            if term in haystack:
                score += 1.0
        if not score:
            continue
        scored.append(RetrievalMatch(chunk=chunk, score=score, strategy="exact"))

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


def _run_ripgrep(codebase_path: Path, query: str, *, top_k: int) -> list[dict[str, object]]:
    args = ["rg", "-n", "-i", "--max-count", "3"]
    for pattern in _ALLOWED_GLOBS:
        args.extend(["-g", pattern])
    args.extend([query, str(codebase_path)])

    result = run_command(args, timeout_seconds=5)
    if result.returncode not in {0, 1} or not result.stdout.strip():
        return []

    parsed: list[dict[str, object]] = []
    for raw_line in result.stdout.splitlines():
        if len(parsed) >= top_k:
            break
        parts = raw_line.split(":", maxsplit=2)
        if len(parts) != 3:
            continue
        file_path, raw_line_number, _line = parts
        try:
            line_number = int(raw_line_number)
        except ValueError:
            continue
        parsed.append({"file_path": file_path, "line_number": line_number})
    return parsed


def _chunk_from_match(file_path: str, line_number: int, *, context_lines: int) -> RetrievalChunk | None:
    path = Path(file_path)
    semantic_chunks = chunk_code_file(path)
    semantic_match = find_chunk_for_line(semantic_chunks, line_number)
    if semantic_match is not None:
        return semantic_match

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    start = max(line_number - context_lines - 1, 0)
    end = min(line_number + context_lines - 1, len(lines) - 1)
    content = "\n".join(lines[start : end + 1]).strip()
    if not content:
        return None
    return RetrievalChunk(
        chunk_id=f"{path}:{start + 1}:{end + 1}",
        corpus="code",
        content=content,
        file_path=str(path),
        start_line=start + 1,
        end_line=end + 1,
        metadata={"chunk_kind": "context_window", "matched_line": line_number},
    )


def _candidate_terms(query: str) -> list[str]:
    terms = [extract_symbol(query).lower()]
    words = re.findall(r"[A-Za-z0-9_.]{4,}", query.lower())
    for word in words:
        if word in terms:
            continue
        terms.append(word)
    return terms


def _direct_file_matches(codebase_path: Path, symbol: str, *, top_k: int) -> list[RetrievalMatch]:
    if not symbol:
        return []

    lowered_symbol = symbol.lower()
    matches: list[RetrievalMatch] = []
    for path in codebase_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".java", ".kt", ".groovy", ".py"}:
            continue
        if path.stem.lower() != lowered_symbol:
            continue
        chunks = chunk_code_file(path)
        if not chunks:
            continue
        matches.append(
            RetrievalMatch(
                chunk=chunks[0],
                score=10.0 - len(matches),
                strategy="exact_file",
            )
        )
        if len(matches) >= top_k:
            break
    return matches


def _preferred_class_candidate(candidates: list[str]) -> str | None:
    if not candidates:
        return None

    scored = sorted(
        candidates,
        key=lambda candidate: (
            0 if candidate.endswith(_PREFERRED_CLASS_SUFFIXES) else 1,
            0 if len(candidate) > 6 else 1,
            -len(candidate),
        ),
    )
    return scored[0]
