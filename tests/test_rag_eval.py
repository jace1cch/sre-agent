"""Tests for retrieval evaluation helpers."""

from pathlib import Path
from uuid import uuid4
import json

from sre_agent.rag.eval import evaluate_matches, run_code_retrieval_eval


def _workspace_dir(name: str) -> Path:
    """Create a workspace-local test directory."""

    path = Path("tests/.tmp") / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_evaluate_matches_reports_file_and_keyword_hits() -> None:
    """Evaluation reports both file and keyword coverage."""

    result = evaluate_matches(
        [
            {
                "file_path": "/tmp/WorkflowExecutor.java",
                "content": "toolResponse getData null guard",
            }
        ],
        expected_files=["WorkflowExecutor.java"],
        expected_keywords=["toolResponse", "null"],
    )

    assert result["file_hit"] is True
    assert result["keyword_hit"] is True


def test_run_code_retrieval_eval_reports_metrics() -> None:
    """Evaluation CLI helpers report aggregate retrieval metrics."""

    tmp_path = _workspace_dir("rag-eval")
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "WorkflowExecutor.java").write_text(
        "public class WorkflowExecutor {\n  // toolResponse null getData\n}\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "rag_golden.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "query": "NullPointerException at WorkflowExecutor.java:234",
                    "expected_files": ["WorkflowExecutor.java"],
                    "expected_keywords": ["toolResponse", "null"],
                    "description": "Synthetic golden example",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_code_retrieval_eval(
        dataset_path=dataset,
        codebase_path=str(codebase),
    )

    assert result["metrics"]["example_count"] == 1
    assert result["metrics"]["file_hit_rate"] == 1.0
