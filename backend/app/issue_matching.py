import os
import re
from collections import Counter, defaultdict
from math import log
from typing import Dict, List, Optional, Set

from .answering import _citation
from .chunking import LANGUAGE_BY_EXTENSION
from .llm import embed_texts
from .retrieval import _cosine, tokenize


GOAL_LABELS = {
    "understand_code": "understand the code",
    "fix_bug": "fix a bug",
    "add_feature": "add a feature",
    "review_prs": "review pull requests",
    "just_learn": "learn the codebase",
}
GOAL_TERMS = {
    "understand_code": "architecture code flow modules",
    "fix_bug": "bug fix error crash regression test",
    "add_feature": "feature enhancement implementation extension test",
    "review_prs": "review pull request code change tests risk",
    "just_learn": "beginner learning setup documentation",
}
GOAL_SIGNALS = {
    "fix_bug": {"bug", "bugs", "bugfix", "defect", "regression"},
    "add_feature": {"feature", "enhancement", "features"},
    "review_prs": {"review", "reviews", "pull request", "code review"},
}
BEGINNER_LABELS = {
    "good first issue", "good-first-issue", "first timers only", "first-timers-only",
    "beginner", "beginner friendly", "help wanted",
}
LANGUAGE_NAMES = {
    "javascript": "JavaScript", "typescript": "TypeScript", "tsx": "TypeScript",
    "python": "Python", "java": "Java", "c": "C", "cpp": "C++",
    "c_sharp": "C#", "go": "Go", "rust": "Rust", "php": "PHP",
    "ruby": "Ruby", "swift": "Swift", "kotlin": "Kotlin", "sql": "SQL",
}
MAX_ISSUES_TO_MATCH = 100


def _normalized_labels(issue: Dict) -> Set[str]:
    return {str(label).strip().lower() for label in issue.get("labels", []) if str(label).strip()}


def _issue_query(issue: Dict, goal: str) -> str:
    title = str(issue.get("title") or "")
    labels = " ".join(issue.get("labels", []))
    body = str(issue.get("body") or "")[:1800]
    return "{} {} {} {} {}".format(title, title, labels, body, GOAL_TERMS.get(goal, ""))[:2600]


def _language_for_path(path: str) -> Optional[str]:
    extension = os.path.splitext(path)[1].lower()
    return LANGUAGE_NAMES.get(LANGUAGE_BY_EXTENSION.get(extension, ""))


def _clean_summary(body: str) -> str:
    value = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[#*_`>~-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:420] + ("…" if len(value) > 420 else "")


class _CodeSearchIndex:
    """Reuse token statistics across issue queries instead of rescanning every file."""

    def __init__(self, chunks: List[Dict]):
        self.chunks = chunks
        self.documents = [
            tokenize("{} {} {}".format(
                chunk.get("text", ""), chunk.get("path", ""), chunk.get("symbol") or ""
            ))
            for chunk in chunks
        ]
        self.term_sets = [set(document) for document in self.documents]
        self.doc_freq = Counter(term for terms in self.term_sets for term in terms)
        self.average_length = sum(len(document) for document in self.documents) / max(len(chunks), 1)
        self.postings = defaultdict(list)
        for index, document in enumerate(self.documents):
            for term, frequency in Counter(document).items():
                self.postings[term].append((index, frequency))

    def rank(self, query: str, query_embedding: Optional[List[float]], top_k: int = 40) -> List[Dict]:
        terms = set(tokenize(query))
        if not terms or not self.chunks:
            return []
        count = len(self.chunks)
        scores = Counter()
        for term in terms:
            frequency = self.doc_freq.get(term, 0)
            if not frequency:
                continue
            idf = log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for index, term_frequency in self.postings[term]:
                document_length = len(self.documents[index])
                denominator = term_frequency + 1.2 * (0.25 + 0.75 * document_length / max(self.average_length, 1))
                scores[index] += idf * term_frequency * 2.2 / denominator
        lexical = sorted(scores, key=scores.get, reverse=True)[:top_k]
        if not lexical:
            return []
        max_score = max(scores[index] for index in lexical) or 1.0
        query_terms = set(tokenize(query))
        result = []
        for index in lexical:
            chunk = self.chunks[index]
            lexical_score = scores[index] / max_score
            similarity = _cosine(query_embedding, chunk.get("embedding") or []) if query_embedding else 0.0
            result.append({
                "chunk": chunk,
                "lexical_score": lexical_score,
                "query_coverage": len(query_terms.intersection(self.term_sets[index])) / max(len(query_terms), 1),
                "similarity": similarity,
            })
        result.sort(
            key=lambda item: 0.62 * item["lexical_score"] + 0.38 * item["similarity"],
            reverse=True,
        )
        return result[:top_k]


def recommend_issues(
    repository: Dict,
    chunks: List[Dict],
    issues: List[Dict],
    profile: Dict,
    limit: int = 12,
) -> List[Dict]:
    if not chunks or not issues:
        return []
    goal = profile.get("onboarding_goal") or "understand_code"
    search_index = _CodeSearchIndex(chunks)
    candidates = sorted(
        issues,
        key=lambda issue: (
            bool(_normalized_labels(issue).intersection(BEGINNER_LABELS)),
            str(issue.get("updated_at", "")),
        ),
        reverse=True,
    )[:MAX_ISSUES_TO_MATCH]
    queries = [_issue_query(issue, goal) for issue in candidates]
    embeddings = embed_texts(queries)
    known_languages = set(profile.get("languages_known") or [])
    beginner = profile.get("experience_level") in {None, "beginner"}
    goal_label = GOAL_LABELS.get(goal, "your goal")
    scored = []

    for index, issue in enumerate(candidates):
        title = str(issue.get("title") or "")
        query_embedding = embeddings[index] if embeddings and index < len(embeddings) else None
        ranked = search_index.rank(queries[index], query_embedding)
        title_terms = set(tokenize(title))
        related = []
        seen_paths = set()
        best_source_score = 0.0
        languages_found = set()
        for item in ranked:
            chunk = item["chunk"]
            path = chunk["path"]
            if path in seen_paths:
                continue
            title_coverage = len(title_terms.intersection(tokenize(path + " " + (chunk.get("symbol") or "") + " " + chunk.get("text", "")))) / max(len(title_terms), 1)
            semantic = item["similarity"]
            query_coverage = item["query_coverage"]
            source_score = min(1.0, 0.58 * title_coverage + 0.22 * min(query_coverage * 4, 1.0) + 0.20 * semantic)
            if title_coverage < 0.12 and query_coverage < 0.025 and semantic < 0.24:
                continue
            seen_paths.add(path)
            best_source_score = max(best_source_score, source_score)
            language = _language_for_path(path)
            if language:
                languages_found.add(language)
            related.append(_citation(repository, chunk))
            if len(related) >= 3:
                break
        if not related:
            continue

        labels = _normalized_labels(issue)
        beginner_match = bool(labels.intersection(BEGINNER_LABELS))
        goal_signals = GOAL_SIGNALS.get(goal, set()) if goal != "review_prs" else set()
        issue_terms = set(tokenize("{} {}".format(title, " ".join(issue.get("labels", [])))))
        goal_match = bool(goal_signals.intersection(issue_terms)) if goal_signals else False
        language_match = bool(known_languages.intersection(languages_found))
        unassigned = int(issue.get("assignee_count", 0)) == 0
        score = 0.78 * best_source_score
        if beginner and beginner_match:
            score += 0.10
        if goal_match:
            score += 0.07
        if language_match:
            score += 0.04
        if unassigned:
            score += 0.02
        reasons = ["Related source found in {}.".format(", ".join(item["path"] for item in related))]
        if beginner and beginner_match:
            reasons.append("The issue has a beginner-friendly label.")
        if goal_match:
            reasons.append("Its labels or title fit your {} goal.".format(goal_label))
        elif goal != "review_prs":
            reasons.append("Ranked with your {} goal in mind.".format(goal_label))
        else:
            reasons.append("Ranked by source relevance; this view recommends issues, not pull requests.")
        matching_languages = sorted(known_languages.intersection(languages_found))
        if matching_languages:
            reasons.append("Related code uses a language you know: {}.".format(", ".join(matching_languages)))
        if unassigned:
            reasons.append("The issue is currently unassigned.")
        body = str(issue.get("body") or "")
        scored.append({
            "number": issue["number"],
            "title": title,
            "summary": _clean_summary(body) or "This issue has no description.",
            "url": issue["html_url"],
            "labels": issue.get("labels", []),
            "updated_at": issue.get("updated_at", ""),
            "assignee_count": int(issue.get("assignee_count", 0)),
            "match_score": max(0, min(99, round(score * 100))),
            "fit_reasons": reasons,
            "related_files": related,
        })

    scored.sort(key=lambda item: (item["match_score"], item["updated_at"]), reverse=True)
    return scored[:limit]
