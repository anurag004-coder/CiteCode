from typing import Callable, Dict, List, Optional, Set

from fastapi import HTTPException

from .answering import _citation, _supporting_quote_is_valid, _verification_note
from .llm import generate_onboarding_guide
from .retrieval import search


def _collect_evidence(question_sets: List[str], chunks: List[Dict]) -> List[Dict]:
    collected = {}
    for query in question_sets:
        results, _ = search(query, chunks, top_k=7)
        for item in results:
            previous = collected.get(item["id"])
            if previous is None or item["retrieval_score"] > previous["retrieval_score"]:
                collected[item["id"]] = item
    ordered = sorted(
        collected.values(), key=lambda item: item["retrieval_score"], reverse=True
    )[:12]
    evidence = []
    for index, item in enumerate(ordered, start=1):
        row = dict(item)
        row["evidence_id"] = "G{}".format(index)
        evidence.append(row)
    return evidence


def _excerpt_sections(
    repository: Dict,
    evidence: List[Dict],
    source_verifier: Optional[Callable[[Dict, Optional[str]], bool]] = None,
) -> List[Dict]:
    sections = []
    seen_paths: Set[str] = set()
    for item in evidence:
        if item["path"] in seen_paths and len(sections) >= 3:
            continue
        seen_paths.add(item["path"])
        text = item["text"].strip()
        if len(text) > 700:
            text = text[:697].rstrip() + "..."
        if not _supporting_quote_is_valid(text, [item], source_verifier):
            continue
        sections.append(
            {
                "title": item.get("symbol") or item["path"],
                "text": text,
                "status": "source_checked",
                "verification_note": _verification_note("English", False),
                "citations": [_citation(repository, item)],
            }
        )
        if len(sections) >= 5:
            break
    return sections


GOAL_LABELS = {
    "understand_code": "Understand the code",
    "fix_bug": "Fix a bug",
    "add_feature": "Add a feature",
    "review_prs": "Review pull requests",
    "just_learn": "Just learn",
}


def build_guide(
    repository: Dict,
    chunks: List[Dict],
    experience_level: str,
    goal: str,
    preferences: Dict,
    source_verifier: Optional[Callable[[Dict, Optional[str]], bool]] = None,
) -> Dict:
    goal_label = GOAL_LABELS.get(goal, goal)
    os_label = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}.get(
        preferences.get("setup_os"), "Linux"
    )
    time_label = {"1_hour": "1 hour", "1_day": "1 day", "1_week": "1 week"}.get(
        preferences.get("time_available"), "1 day"
    )
    queries = [
        "README project overview architecture setup install run entry point modules",
        "{} architecture modules setup request path tests first task".format(goal_label),
        "{} setup install run prerequisites environment variables Docker".format(os_label),
    ]
    evidence = _collect_evidence(queries, chunks)
    if not evidence:
        raise HTTPException(
            status_code=422,
            detail="No useful code or documentation evidence was found for this guide.",
        )

    guide_preferences = {
        **preferences,
        "goal": goal_label,
        "setup_os": os_label,
        "time_available": time_label,
    }
    generated = generate_onboarding_guide(experience_level, goal_label, guide_preferences, evidence)
    if generated is None:
        sections = _excerpt_sections(repository, evidence, source_verifier)
        return {
            "repo_id": repository["id"],
            "repository": repository["full_name"],
            "commit_sha": repository["commit_sha"],
            "mode": "extractive",
            "title": "Getting started with {}".format(repository["name"]),
            "summary": "These source excerpts are a starting map. A generated guide is unavailable right now.",
            "sections": sections,
            "gaps": ["Generated setup instructions and a personalized learning path are unavailable."],
            "searched_paths": list(dict.fromkeys(item["path"] for item in evidence)),
        }

    valid_by_id = {item["evidence_id"]: item for item in evidence}
    sections = []
    for raw in generated.get("sections", [])[:8]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()[:100]
        text = str(raw.get("text", "")).strip()[:2000]
        if not title or not text:
            continue
        raw_ids = raw.get("evidence_ids", [])
        if not isinstance(raw_ids, list):
            raw_ids = []
        cited = []
        seen = set()
        for evidence_id in raw_ids:
            evidence_id = str(evidence_id)
            if evidence_id in valid_by_id and evidence_id not in seen:
                cited.append(valid_by_id[evidence_id])
                seen.add(evidence_id)

        label = str(raw.get("label", "FROM_CODE")).upper()
        if label == "ASSUMPTION":
            status = "assumption"
            note = "The guide marks this explanation as an inference. Check it before relying on it."
        elif cited and _supporting_quote_is_valid(
            str(raw.get("evidence_quote", "")).strip(), cited, source_verifier
        ):
            status = "source_checked"
            note = _verification_note("English", False)
        else:
            # Keep generated repository facts tied to a live, exact source excerpt.
            continue

        sections.append(
            {
                "title": title,
                "text": text,
                "status": status,
                "verification_note": note,
                "citations": [_citation(repository, item) for item in cited],
            }
        )

    if not sections:
        sections = _excerpt_sections(repository, evidence, source_verifier)
        mode = "extractive"
    else:
        mode = "generated"

    gaps = generated.get("gaps", [])
    if not isinstance(gaps, list):
        gaps = []
    gaps = [str(item).strip()[:300] for item in gaps if str(item).strip()][:8]
    return {
        "repo_id": repository["id"],
        "repository": repository["full_name"],
        "commit_sha": repository["commit_sha"],
        "mode": mode,
        "title": str(generated.get("title") or "Getting started with {}".format(repository["name"]))[:120],
        "summary": str(generated.get("summary") or "A source-linked starting guide for this repository.")[:600],
        "sections": sections,
        "gaps": gaps,
        "searched_paths": list(dict.fromkeys(item["path"] for item in evidence)),
    }
