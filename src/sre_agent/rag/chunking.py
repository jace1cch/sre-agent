"""Chunking helpers for code and incident retrieval."""

from collections.abc import Iterable
from pathlib import Path
import json
import re

from sre_agent.rag.models import RetrievalChunk

_JAVA_METHOD_PATTERN = re.compile(
    r"^\s*(public|private|protected|static|final|synchronized|abstract|default)\s+"
    r"[\w<>\[\], ?]+\s+\w+\s*\(",
)
_CLASS_PATTERN = re.compile(r"\b(class|interface|enum)\s+([A-Z]\w*)")
_ALLOWED_SUFFIXES = {".java", ".kt", ".groovy", ".xml", ".yml", ".yaml", ".properties", ".py"}
_SKIPPED_PARTS = {".git", ".venv", "node_modules", "dist", "build", "target", "__pycache__"}


def iter_code_chunks(root: Path) -> list[RetrievalChunk]:
    """Return semantic code chunks for the configured codebase."""

    chunks: list[RetrievalChunk] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIPPED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in _ALLOWED_SUFFIXES:
            continue
        chunks.extend(chunk_code_file(path))
    return chunks


def chunk_code_file(path: Path) -> list[RetrievalChunk]:
    """Chunk one code file along pragmatic semantic boundaries."""

    if path.suffix.lower() == ".java":
        return chunk_java_file(path)
    return chunk_text_file(path)


def chunk_java_file(path: Path) -> list[RetrievalChunk]:
    """Chunk a Java file by method boundaries."""

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    class_name = _class_name(lines, path)
    chunks: list[RetrievalChunk] = []
    start: int | None = None
    brace_depth = 0

    for index, line in enumerate(lines):
        if start is None and _JAVA_METHOD_PATTERN.match(line):
            start = index
            brace_depth = line.count("{") - line.count("}")
            if brace_depth <= 0:
                chunk = _build_chunk_from_lines(
                    path=path,
                    lines=lines,
                    start=start,
                    end=index,
                    class_name=class_name,
                    chunk_kind="method",
                )
                if chunk is not None:
                    chunks.append(chunk)
                start = None
            continue

        if start is None:
            continue

        brace_depth += line.count("{") - line.count("}")
        if brace_depth > 0:
            continue

        chunk = _build_chunk_from_lines(
            path=path,
            lines=lines,
            start=start,
            end=index,
            class_name=class_name,
            chunk_kind="method",
        )
        if chunk is not None:
            chunks.append(chunk)
        start = None
        brace_depth = 0

    if chunks:
        return chunks
    return chunk_text_file(path)


def chunk_text_file(path: Path, window_lines: int = 80) -> list[RetrievalChunk]:
    """Chunk a non-Java file into fixed line windows."""

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    chunks: list[RetrievalChunk] = []
    for start in range(0, len(lines), window_lines):
        end = min(start + window_lines, len(lines)) - 1
        chunk = _build_chunk_from_lines(
            path=path,
            lines=lines,
            start=start,
            end=end,
            class_name=None,
            chunk_kind="window",
        )
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def chunk_incidents_jsonl(path: Path) -> list[RetrievalChunk]:
    """Chunk incident history one record at a time."""

    if not path.exists():
        return []

    chunks: list[RetrievalChunk] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        incident = payload.get("incident") or {}
        diagnosis = payload.get("diagnosis") or {}
        findings = incident.get("findings") or []
        finding_codes = [str(item.get("code") or "") for item in findings]
        finding_summaries = [str(item.get("summary") or "") for item in findings]
        suggested_fixes = diagnosis.get("suggested_fixes") or []
        fix_descriptions = [
            str(item.get("description") or item)
            for item in suggested_fixes
            if str(item.get("description") if isinstance(item, dict) else item).strip()
        ]

        content = "\n".join(
            [
                f"Service: {incident.get('service_name', '')}",
                f"Severity: {incident.get('severity', '')}",
                f"Observed at: {incident.get('observed_at', '')}",
                f"Root cause: {diagnosis.get('root_cause', '')}",
                f"Summary: {diagnosis.get('summary', '')}",
                f"Finding codes: {' '.join(finding_codes)}",
                f"Finding summaries: {' '.join(finding_summaries)}",
                f"Suggested fixes: {' '.join(fix_descriptions)}",
            ]
        ).strip()
        chunks.append(
            RetrievalChunk(
                chunk_id=f"incident:{line_number}",
                corpus="incident_history",
                content=content,
                file_path=str(path),
                start_line=line_number,
                end_line=line_number,
                metadata={
                    "line_number": line_number,
                    "incident": incident,
                    "diagnosis": diagnosis,
                },
            )
        )
    return chunks


def find_chunk_for_line(chunks: Iterable[RetrievalChunk], line_number: int) -> RetrievalChunk | None:
    """Return the chunk that contains the given line number."""

    for chunk in chunks:
        if chunk.start_line is None or chunk.end_line is None:
            continue
        if chunk.start_line <= line_number <= chunk.end_line:
            return chunk
    return None


def _class_name(lines: list[str], path: Path) -> str:
    for line in lines:
        match = _CLASS_PATTERN.search(line)
        if match is None:
            continue
        return match.group(2)
    return path.stem


def _build_chunk_from_lines(
    *,
    path: Path,
    lines: list[str],
    start: int,
    end: int,
    class_name: str | None,
    chunk_kind: str,
) -> RetrievalChunk | None:
    if start < 0 or end < start or start >= len(lines):
        return None

    content = "\n".join(lines[start : end + 1]).strip()
    if not content:
        return None

    prefix = f"Class: {class_name}\n" if class_name else ""
    start_line = start + 1
    end_line = end + 1
    return RetrievalChunk(
        chunk_id=f"{path}:{start_line}:{end_line}",
        corpus="code",
        content=f"{prefix}{content}".strip(),
        file_path=str(path),
        start_line=start_line,
        end_line=end_line,
        metadata={"chunk_kind": chunk_kind, "class_name": class_name},
    )
