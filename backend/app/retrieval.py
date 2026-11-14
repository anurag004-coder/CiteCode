import math
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from .config import MIN_COSINE_SIMILARITY, MIN_LEXICAL_COVERAGE
from .llm import embed_query


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for",
    "from", "how", "i", "in", "is", "it", "me", "of", "on", "or", "the",
    "this", "to", "what", "when", "where", "which", "who", "why", "with",
}
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")


def tokenize(value: str) -> List[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    tokens = [token.lower() for token in TOKEN_PATTERN.findall(value)]
    return [token for token in tokens if token not in STOP_WORDS]


def _cosine(left: List[float], right: List[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


def rank_chunks(
    question: str,
    chunks: List[Dict],
    top_k: int = 8,
    method: str = "hybrid",
    query_embedding: Optional[List[float]] = None,
    embed_if_missing: bool = True,
) -> Tuple[List[Dict], bool]:
    """Rank code chunks with keyword, semantic, or reciprocal-rank-fusion retrieval."""
    query_tokens = tokenize(question)
    query_terms = set(query_tokens)
    documents = [tokenize(chunk["text"] + " " + chunk["path"] + " " + (chunk.get("symbol") or "")) for chunk in chunks]
    count = len(documents)
    if not count:
        return [], False

    doc_freq = Counter(term for doc in documents for term in set(doc))
    avg_length = sum(len(doc) for doc in documents) / max(count, 1)
    lexical_scores = {}
    lexical_coverage = {}
    for chunk, doc in zip(chunks, documents):
        frequencies = Counter(doc)
        score = 0.0
        for term in query_terms:
            tf = frequencies.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (count - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denominator = tf + 1.2 * (0.25 + 0.75 * len(doc) / max(avg_length, 1))
            score += idf * tf * 2.2 / denominator
        lexical_scores[chunk["id"]] = score
        lexical_coverage[chunk["id"]] = (
            len(query_terms.intersection(set(doc))) / len(query_terms) if query_terms else 0.0
        )

    lexical_ranked = sorted(
        [chunk for chunk in chunks if lexical_scores[chunk["id"]] > 0],
        key=lambda item: lexical_scores[item["id"]],
        reverse=True,
    )
    ranked_lists = [lexical_ranked] if lexical_ranked else []
    if query_embedding is None and embed_if_missing and method in {"semantic", "hybrid"}:
        query_embedding = embed_query(question)
    similarities = {}
    if query_embedding:
        semantic_ranked = []
        for chunk in chunks:
            vector = chunk.get("embedding")
            similarity = _cosine(query_embedding, vector) if vector else 0.0
            similarities[chunk["id"]] = similarity
            semantic_ranked.append(chunk)
        semantic_ranked = [item for item in semantic_ranked if similarities[item["id"]] > 0]
        semantic_ranked.sort(key=lambda item: similarities[item["id"]], reverse=True)
        if semantic_ranked:
            ranked_lists.append(semantic_ranked)

    if method == "keyword":
        results = lexical_ranked[:top_k]
    elif method == "semantic":
        results = []
        if query_embedding:
            results = sorted(
                [chunk for chunk in chunks if similarities.get(chunk["id"], 0.0) > 0],
                key=lambda item: similarities[item["id"]],
                reverse=True,
            )[:top_k]
    elif method == "hybrid" and ranked_lists:
        rrf_scores = Counter()
        for ranked in ranked_lists:
            for rank, chunk in enumerate(ranked, start=1):
                rrf_scores[chunk["id"]] += 1 / (60 + rank)
        results = sorted(
            chunks,
            key=lambda item: (rrf_scores[item["id"]], lexical_scores[item["id"]]),
            reverse=True,
        )[:top_k]
    else:
        results = []

    if not results:
        return [], False
    sufficient = any(
        lexical_coverage[item["id"]] >= MIN_LEXICAL_COVERAGE
        or similarities.get(item["id"], 0.0) >= MIN_COSINE_SIMILARITY
        for item in results
    )
    enriched = []
    rrf_scores = Counter()
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            rrf_scores[chunk["id"]] += 1 / (60 + rank)
    for item in results:
        row = dict(item)
        row["retrieval_score"] = round(
            similarities.get(item["id"], 0.0) if method == "semantic"
            else lexical_scores[item["id"]] if method == "keyword"
            else rrf_scores[item["id"]], 6
        )
        row["lexical_coverage"] = round(lexical_coverage[item["id"]], 3)
        row["similarity"] = round(similarities.get(item["id"], 0.0), 3)
        enriched.append(row)
    return enriched, sufficient


def search(question: str, chunks: List[Dict], top_k: int = 8) -> Tuple[List[Dict], bool]:
    return rank_chunks(question, chunks, top_k=top_k, method="hybrid")


def build_search_corpus(
    repository: Dict,
    chunks: List[Dict],
    issues: List[Dict],
    commits: List[Dict],
) -> List[Dict]:
    """Combine source chunks with issue and commit records for repository Q&A."""
    corpus = []
    for chunk in chunks:
        item = dict(chunk)
        item["reference_key"] = item["path"]
        corpus.append(item)

    for issue in issues:
        if issue.get("state", "open") != "open":
            continue
        number = int(issue["number"])
        title = str(issue.get("title") or "").strip()
        labels = issue.get("labels") or []
        path = "Issue #{}: {}".format(number, title)
        text = "Issue #{}\nTitle: {}\nLabels: {}\nUpdated: {}\n\n{}".format(
            number, title, ", ".join(str(label) for label in labels),
            issue.get("updated_at", ""), issue.get("body", ""),
        ).strip()
        corpus.append({
            "id": "issue:{}".format(number),
            "repo_id": repository["id"],
            "source_type": "issue",
            "reference_key": "issue:{}".format(number),
            "path": path,
            "symbol": "Issue #{}".format(number),
            "start_line": None,
            "end_line": None,
            "commit_sha": repository["commit_sha"],
            "text": text,
            "content_hash": "",
            "embedding": None,
            "source_url": issue.get("html_url", ""),
            "issue_number": number,
            "issue_title": title,
            "issue_body": str(issue.get("body") or ""),
        })

    for commit in commits:
        sha = str(commit.get("sha") or "")
        if not sha:
            continue
        message = str(commit.get("message") or "").strip()
        first_line = message.splitlines()[0] if message else "Commit"
        path = "Commit {}: {}".format(sha[:10], first_line)
        text = "Commit {}\nMessage: {}\nAuthor: {}\nCommitted: {}".format(
            sha, message, commit.get("author", "Unknown"), commit.get("committed_at", "")
        )
        corpus.append({
            "id": "commit:{}".format(sha),
            "repo_id": repository["id"],
            "source_type": "commit",
            "reference_key": "commit:{}".format(sha),
            "path": path,
            "symbol": "Commit {}".format(sha[:10]),
            "start_line": None,
            "end_line": None,
            "commit_sha": sha,
            "text": text,
            "content_hash": "",
            "embedding": None,
            "source_url": commit.get("html_url", ""),
            "commit_message": message,
        })
    return corpus
