"""Evaluation helpers for operational retrieval."""

import json
import argparse
from pathlib import Path

from sre_agent.core.settings import AgentSettings, get_settings
from sre_agent.rag import CodeRetriever
from sre_agent.rag.models import GoldenExample


def load_golden_examples(path: str | Path) -> list[GoldenExample]:
    """Load a golden retrieval dataset from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GoldenExample(**item) for item in payload]


def evaluate_matches(
    results: list[dict[str, object]],
    *,
    expected_files: list[str],
    expected_keywords: list[str],
) -> dict[str, object]:
    """Evaluate one retrieval result set against a golden example."""

    matched_files = {Path(str(item.get("file_path", ""))).name for item in results}
    aggregated_content = "\n".join(str(item.get("content", "")) for item in results).lower()
    file_hit = any(Path(expected_file).name in matched_files for expected_file in expected_files)
    keyword_hit = all(keyword.lower() in aggregated_content for keyword in expected_keywords)
    return {
        "file_hit": file_hit,
        "keyword_hit": keyword_hit,
        "retrieved_files": sorted(matched_files),
    }


def run_code_retrieval_eval(
    *,
    dataset_path: str | Path,
    codebase_path: str,
    settings: AgentSettings | None = None,
) -> dict[str, object]:
    """Run the hybrid code retriever against a golden dataset."""

    examples = load_golden_examples(dataset_path)
    base_settings = settings or get_settings()
    settings = base_settings.model_copy(
        update={
            "codebase_path": codebase_path,
            "repository_path": codebase_path,
        }
    )
    retriever = CodeRetriever(settings)

    per_example: list[dict[str, object]] = []
    file_hits = 0
    keyword_hits = 0
    for example in examples:
        result = retriever.search(example.query)
        matches = result.get("data", {}).get("matches", [])
        evaluation = evaluate_matches(
            matches,
            expected_files=example.expected_files,
            expected_keywords=example.expected_keywords,
        )
        file_hits += int(evaluation["file_hit"])
        keyword_hits += int(evaluation["keyword_hit"])
        per_example.append(
            {
                "query": example.query,
                "description": example.description,
                "status": result["status"],
                "summary": result["summary"],
                **evaluation,
            }
        )

    total = len(examples) or 1
    return {
        "dataset_path": str(dataset_path),
        "codebase_path": codebase_path,
        "examples": per_example,
        "metrics": {
            "example_count": len(examples),
            "file_hit_rate": round(file_hits / total, 4),
            "keyword_hit_rate": round(keyword_hits / total, 4),
        },
    }


def main() -> None:
    """Run the retrieval evaluation CLI."""

    parser = argparse.ArgumentParser(description="Evaluate the hybrid operational RAG retriever.")
    parser.add_argument("--dataset", default="data/eval/rag_golden.json", help="Path to the golden dataset JSON file.")
    parser.add_argument("--codebase-path", required=True, help="Codebase path to evaluate against.")
    args = parser.parse_args()

    result = run_code_retrieval_eval(
        dataset_path=args.dataset,
        codebase_path=args.codebase_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
