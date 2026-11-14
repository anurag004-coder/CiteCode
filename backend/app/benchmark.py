import json
from pathlib import Path
from typing import Dict, List, Optional

from .answering import answer_question
from .llm import embed_texts
from .retrieval import build_search_corpus, rank_chunks


DATASET_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "retrieval_dataset.json"


def load_dataset() -> Dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _metrics(rows: List[Dict], top_k: int) -> Dict:
    answerable = [row for row in rows if row["answerable"]]
    if not answerable:
        return {"recall_at_k": 0, "precision_at_k": 0, "hit_rate_at_k": 0, "mrr": 0}
    recalls, precisions, hits, reciprocal_ranks = [], [], [], []
    for row in answerable:
        expected = set(row.get("expected_refs", row.get("expected_paths", [])))
        paths = row["paths"]
        found = expected.intersection(paths)
        recalls.append(len(found) / len(expected) if expected else 0)
        relevant_ranks = [index for index, path in enumerate(paths, start=1) if path in expected]
        hits.append(1 if relevant_ranks else 0)
        precisions.append(len([path for path in paths[:top_k] if path in expected]) / max(1, top_k))
        reciprocal_ranks.append(1 / relevant_ranks[0] if relevant_ranks else 0)
    return {
        "recall_at_k": round(sum(recalls) / len(recalls), 4),
        "precision_at_k": round(sum(precisions) / len(precisions), 4),
        "hit_rate_at_k": round(sum(hits) / len(hits), 4),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
    }


def evaluate_repository(
    repo: Dict,
    chunks: List[Dict],
    top_k: int = 5,
    dataset: Optional[Dict] = None,
    issues: Optional[List[Dict]] = None,
    commits: Optional[List[Dict]] = None,
    include_answer_quality: bool = False,
    source_verifier=None,
) -> Dict:
    builtin_dataset = dataset is None
    dataset = dataset or load_dataset()
    cases = dataset["cases"]
    if include_answer_quality and len(cases) > 40:
        raise ValueError("Answer-quality evaluation is limited to 40 questions per run to bound model and GitHub requests.")
    corpus = chunks if builtin_dataset else build_search_corpus(repo, chunks, issues or [], commits or [])
    known_refs = {
        chunk.get("reference_key", chunk["path"])
        for chunk in corpus
    }
    expected_labels = [
        reference
        for case in cases
        for reference in case.get("expected_refs", case.get("expected_paths", []))
    ]
    covered_labels = sum(1 for reference in expected_labels if reference in known_refs)
    path_coverage = covered_labels / max(1, len(expected_labels))
    if builtin_dataset and path_coverage < 0.55:
        raise ValueError(
            "This benchmark is labeled for the Codebase Whisperer source tree. "
            "Index that repository first (current gold-path coverage: {}%).".format(round(path_coverage * 100))
        )

    questions = [case["question"] for case in cases]
    corpus_has_embeddings = any(chunk.get("embedding") for chunk in corpus)
    query_vectors = embed_texts(questions) if corpus_has_embeddings else None
    method_rows = {"keyword": [], "semantic": [], "hybrid": []}
    case_rows = []
    answerability_rows = []
    answer_quality_rows = []

    for index, case in enumerate(cases):
        vector: Optional[List[float]] = query_vectors[index] if query_vectors and index < len(query_vectors) else None
        ranked_for_case = {}
        method_results = {}
        hybrid_results = []
        for method in ("keyword", "semantic", "hybrid"):
            results, sufficient = rank_chunks(
                case["question"], corpus, top_k=top_k, method=method,
                query_embedding=vector, embed_if_missing=False,
            )
            if method == "hybrid":
                hybrid_results = results
            ranked_chunk_paths = [item.get("reference_key", item["path"]) for item in results]
            paths = list(dict.fromkeys(ranked_chunk_paths))
            expected_refs = case.get("expected_refs", case.get("expected_paths", []))
            ranked_for_case[method] = {"paths": paths, "sufficient": sufficient}
            method_results[method] = {
                "top_paths": paths,
                "matched_paths": sorted(set(paths).intersection(expected_refs)),
            }
            if method != "semantic" or (vector and corpus_has_embeddings):
                method_rows[method].append({
                    "answerable": case["answerable"],
                    "expected_refs": expected_refs,
                    "paths": ranked_chunk_paths,
                })

        hybrid_sufficient = ranked_for_case["hybrid"]["sufficient"]
        answerability_rows.append(hybrid_sufficient == case["answerable"])
        case_result = {
            "id": case["id"],
            "category": case.get("category", "custom"),
            "question": case["question"],
            "answerable": case["answerable"],
            "expected_refs": case.get("expected_refs", case.get("expected_paths", [])),
            "hybrid_sufficient": hybrid_sufficient,
            "methods": method_results,
        }
        if include_answer_quality:
            answer = answer_question(
                case["question"], repo, hybrid_results, hybrid_sufficient,
                "English", source_verifier=source_verifier, include_diagnostics=True,
            )
            diagnostics = answer.get("_quality_diagnostics", {})
            citations = [
                citation
                for claim in answer.get("claims", [])
                if claim.get("status") == "source_checked"
                for citation in claim.get("citations", [])
            ]
            citation_refs = [citation.get("reference_key") for citation in citations if citation.get("reference_key")]
            expected_refs = set(case.get("expected_refs", case.get("expected_paths", [])))
            if case["answerable"]:
                answer_quality_rows.append({
                    "answerable": True,
                    "expected_refs": expected_refs,
                    "citation_refs": citation_refs,
                    "generated_fact_claims": diagnostics.get("generated_fact_claims", 0),
                    "source_checked_fact_claims": diagnostics.get("source_checked_fact_claims", 0),
                    "rejected_fact_claims": diagnostics.get("rejected_fact_claims", 0),
                    "generation_performed": diagnostics.get("generation_performed", False),
                })
            else:
                answer_quality_rows.append({
                    "answerable": False,
                    "expected_refs": set(),
                    "citation_refs": citation_refs,
                    "generated_fact_claims": diagnostics.get("generated_fact_claims", 0),
                    "source_checked_fact_claims": diagnostics.get("source_checked_fact_claims", 0),
                    "rejected_fact_claims": diagnostics.get("rejected_fact_claims", 0),
                    "generation_performed": diagnostics.get("generation_performed", False),
                })
            case_result["answer_quality"] = {
                "mode": answer["mode"],
                "citation_refs": citation_refs,
                "generated_fact_claims": diagnostics.get("generated_fact_claims", 0),
                "source_checked_fact_claims": diagnostics.get("source_checked_fact_claims", 0),
                "rejected_fact_claims": diagnostics.get("rejected_fact_claims", 0),
                "generation_performed": diagnostics.get("generation_performed", False),
            }
        case_rows.append(case_result)

    methods = {}
    for method, rows in method_rows.items():
        methods[method] = {
            "available": bool(rows) if method == "semantic" else True,
            **(_metrics(rows, top_k) if rows else {}),
            "scored_answerable_cases": sum(1 for row in rows if row["answerable"]),
        }
    unanswerable = [row for row in case_rows if not row["answerable"]]
    answerable = [row for row in case_rows if row["answerable"]]
    answer_quality = {"available": False, "reason": "Enable answer-quality evaluation to generate and check answers."}
    if include_answer_quality:
        answerable_quality = [row for row in answer_quality_rows if row["answerable"]]
        unanswerable_quality = [row for row in answer_quality_rows if not row["answerable"]]
        citation_refs = [reference for row in answerable_quality for reference in row["citation_refs"]]
        correct_citations = sum(
            1 for row in answerable_quality for reference in row["citation_refs"]
            if reference in row["expected_refs"]
        )
        # Micro citation precision and recall are scored against each case's labeled references.
        citation_precision_denominator = len(citation_refs)
        citation_recall_numerator = sum(
            len(set(row["citation_refs"]).intersection(row["expected_refs"]))
            for row in answerable_quality
        )
        citation_recall_denominator = sum(len(row["expected_refs"]) for row in answerable_quality)
        generated_fact_total = sum(row["generated_fact_claims"] for row in answer_quality_rows)
        rejected_fact_total = sum(row["rejected_fact_claims"] for row in answer_quality_rows)
        hallucination_cases = sum(1 for row in unanswerable_quality if row["generated_fact_claims"] > 0)
        model_available = any(row["generation_performed"] for row in answer_quality_rows)
        answer_quality = {
            "available": model_available,
            "reason": None if model_available else "OpenAI answer generation was unavailable for this run.",
            "citation_precision": (
                round(correct_citations / citation_precision_denominator, 4)
                if model_available and citation_precision_denominator else None
            ),
            "citation_recall": (
                round(citation_recall_numerator / citation_recall_denominator, 4)
                if model_available and citation_recall_denominator else None
            ),
            "source_check_rejection_rate": (
                round(rejected_fact_total / generated_fact_total, 4)
                if model_available and generated_fact_total else None
            ),
            "unanswerable_hallucination_rate": (
                round(hallucination_cases / len(unanswerable_quality), 4)
                if model_available and unanswerable_quality else None
            ),
            "evaluated_answerable_cases": len(answerable_quality),
            "evaluated_unanswerable_cases": len(unanswerable_quality),
            "generated_fact_claims": generated_fact_total,
            "rejected_fact_claims": rejected_fact_total,
            "note": "Hallucination is estimated on labeled unanswerable questions; citation scores compare cited references with the benchmark labels and do not prove semantic correctness.",
        }
    return {
        "repository": repo["full_name"],
        "commit_sha": repo["commit_sha"],
        "dataset": dataset.get("name", "Repository benchmark"),
        "dataset_description": dataset.get("description", "User-labeled repository question set."),
        "top_k": top_k,
        "total_cases": len(cases),
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "gold_path_coverage": round(path_coverage, 4),
        "hybrid_answerability_accuracy": round(sum(answerability_rows) / max(1, len(answerability_rows)), 4),
        "answerable_sufficient_rate": round(sum(1 for row in answerable if row["hybrid_sufficient"]) / max(1, len(answerable)), 4),
        "unanswerable_refusal_rate": round(sum(1 for row in unanswerable if not row["hybrid_sufficient"]) / max(1, len(unanswerable)), 4),
        "methods": methods,
        "answer_quality": answer_quality,
        "cases": case_rows,
    }
