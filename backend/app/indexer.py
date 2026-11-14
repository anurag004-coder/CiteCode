from datetime import datetime, timezone
from typing import Dict, List

from fastapi import HTTPException

from . import db
from .chunking import chunk_file
from .config import MAX_CHUNKS_PER_REPO
from .github import GitHubClient, parse_github_url
from .llm import embed_texts


def index_repository(repository_url: str) -> Dict:
    owner, name = parse_github_url(repository_url)
    repo_id = (owner + "/" + name).lower()
    github = GitHubClient()
    previous_files = db.get_indexed_files(repo_id)
    previous_chunks = db.get_chunks(repo_id) if previous_files else []
    previous_chunks_by_path = {}
    for chunk in previous_chunks:
        previous_chunks_by_path.setdefault(chunk["path"], []).append(chunk)
    snapshot = github.index(owner, name, reusable_files=previous_files)
    repo_id = snapshot["full_name"].lower()
    if previous_files and snapshot.get("download_failures"):
        failed = ", ".join(snapshot["download_failures"][:5])
        raise HTTPException(
            status_code=502,
            detail="Could not download changed GitHub files ({}); the previous index was kept intact.".format(failed),
        )
    issues = None
    issue_warning = None
    try:
        issues = github.fetch_open_issues(owner, name)
    except HTTPException as error:
        issue_warning = "Open issues could not be refreshed: {}".format(error.detail)
    commits = None
    commit_warning = None
    try:
        commits = github.fetch_recent_commits(owner, name, snapshot["default_branch"])
    except HTTPException as error:
        commit_warning = "Commit history could not be refreshed: {}".format(error.detail)

    chunks = []
    changed_chunks = []
    file_blob_shas = snapshot["file_blob_shas"]
    for path, text in snapshot["files"].items():
        old_file = previous_files.get(path)
        if old_file and old_file.get("blob_sha") == file_blob_shas.get(path):
            for old_chunk in previous_chunks_by_path.get(path, []):
                reused = dict(old_chunk)
                reused["commit_sha"] = snapshot["commit_sha"]
                chunks.append(reused)
            continue
        new_chunks = chunk_file(repo_id, path, snapshot["commit_sha"], text)
        chunks.extend(new_chunks)
        changed_chunks.extend(new_chunks)
        if len(chunks) > MAX_CHUNKS_PER_REPO:
            raise HTTPException(
                status_code=413,
                detail="This repository creates too many chunks for the first version. Try a smaller repository.",
            )
    if not chunks:
        raise HTTPException(status_code=422, detail="No supported code or Markdown files were found.")

    embedding_warning = None
    if changed_chunks:
        embeddings = embed_texts([chunk.text for chunk in changed_chunks])
        if embeddings is None:
            embedding_warning = "OpenAI embeddings are unavailable for changed files; search will use keyword matching for those chunks."
        else:
            for chunk, embedding in zip(changed_chunks, embeddings):
                chunk.embedding = embedding

    records = [chunk.to_record() if hasattr(chunk, "to_record") else chunk for chunk in chunks]
    file_records = {
        path: {"blob_sha": file_blob_shas[path], "content": content}
        for path, content in snapshot["files"].items()
        if file_blob_shas.get(path)
    }
    repository = {
        "id": repo_id,
        "full_name": snapshot["full_name"],
        "owner": snapshot["owner"],
        "name": snapshot["name"],
        "url": snapshot["url"],
        "default_branch": snapshot["default_branch"],
        "commit_sha": snapshot["commit_sha"],
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(snapshot["files"]),
        "chunk_count": len(records),
    }
    issue_count = len(issues) if issues is not None else int((db.get_repository(repo_id) or {}).get("issue_count", 0))
    commit_count = len(commits) if commits is not None else db.count_commits(repo_id)
    db.save_index(repository, records, issues, file_records)
    if commits is not None:
        db.save_commit_history(repo_id, commits)
    warnings = [warning for warning in (embedding_warning, issue_warning, commit_warning) if warning]
    return {
        "repo_id": repo_id,
        "full_name": snapshot["full_name"],
        "commit_sha": snapshot["commit_sha"],
        "default_branch": snapshot["default_branch"],
        "file_count": repository["file_count"],
        "chunk_count": repository["chunk_count"],
        "issue_count": issue_count,
        "commit_count": commit_count,
        "skipped_files": snapshot["skipped_files"],
        "vector_search": any(record.get("embedding") for record in records),
        "warning": " ".join(warnings) or None,
    }
