"""Refresh indexed repositories against their latest default-branch commit."""
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import HTTPException

from . import db
from .changes import build_change_snapshot
from .github import GitHubClient
from .indexer import index_repository


logger = logging.getLogger(__name__)
_LOCKS_GUARD = threading.Lock()
_REPOSITORY_LOCKS = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repository_lock(repo_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _REPOSITORY_LOCKS.setdefault(repo_id, threading.Lock())


def refresh_repository(repo_id: str, explanation_language: str = "English") -> Optional[Dict]:
    """Check GitHub and refresh a repository snapshot if its default branch advanced.

    Returns the saved change snapshot. The lock prevents the scheduler and a manual
    refresh from rebuilding the same snapshot at the same time in one app process.
    """
    lock = _repository_lock(repo_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A refresh for this repository is already running.")

    checked_at = _now()
    latest_sha = None
    repo = db.get_repository(repo_id.lower())
    if repo is None:
        lock.release()
        raise HTTPException(status_code=404, detail="Repository is not indexed.")

    db.update_repository_sync_state(repo["id"], "syncing", checked_at)
    try:
        github = GitHubClient()
        latest = github.latest_branch_head(repo["owner"], repo["name"])
        latest_sha = latest["sha"]
        checked_at = _now()
        base_sha = repo["commit_sha"]

        if latest_sha == base_sha:
            recent_commits = github.fetch_recent_commits(
                repo["owner"], repo["name"], latest["default_branch"]
            )
            db.save_commit_history(repo["id"], recent_commits)
            open_issues = github.fetch_open_issues(repo["owner"], repo["name"])
            db.save_issues(repo["id"], open_issues, checked_at)
            existing = db.get_change_snapshot(repo["id"])
            if existing:
                db.mark_changes_checked(repo["id"], checked_at)
            else:
                db.save_change_snapshot(
                    repo["id"],
                    {
                        "base_sha": base_sha,
                        "head_sha": base_sha,
                        "synced_at": checked_at,
                        "checked_at": checked_at,
                        "summary": "The indexed snapshot is already at the latest branch commit. No newer commits or file changes were found.",
                        "mode": "computed",
                        "verification_note": "The latest branch SHA from GitHub matches the indexed commit SHA.",
                        "comparison_url": "",
                        "commit_total": 0,
                        "file_total": 0,
                        "commits": [],
                        "files": [],
                        "gaps": [],
                    },
                )
            db.update_repository_sync_state(
                repo["id"], "current", checked_at, latest_sha=latest_sha,
                last_success_at=checked_at, error=None,
            )
            return db.get_change_snapshot(repo["id"])

        db.update_repository_sync_state(
            repo["id"], "stale", checked_at, latest_sha=latest_sha, error=None
        )
        comparison = github.compare_commits(repo["owner"], repo["name"], base_sha, latest_sha)
        indexed = index_repository(repo["url"])
        head_sha = indexed["commit_sha"]
        if head_sha != latest_sha:
            try:
                comparison = github.compare_commits(repo["owner"], repo["name"], base_sha, head_sha)
            except HTTPException:
                comparison = {
                    "status": "branch_advanced_during_refresh",
                    "ahead_by": 0,
                    "total_commits": 0,
                    "total_files": 0,
                    "commits": [],
                    "files": [],
                    "compare_url": "https://github.com/{}/{}/compare/{}...{}".format(
                        repo["owner"], repo["name"], base_sha, head_sha
                    ),
                    "gaps": ["The branch advanced while refreshing, and GitHub could not return the final comparison."],
                }

        snapshot = build_change_snapshot(base_sha, head_sha, comparison, explanation_language)
        if comparison.get("gaps"):
            snapshot["gaps"] = list(snapshot["gaps"]) + comparison["gaps"]
        if indexed.get("warning"):
            snapshot["gaps"] = list(snapshot["gaps"]) + [indexed["warning"]]
        db.save_change_snapshot(repo["id"], snapshot)
        db.save_commit_history(repo["id"], snapshot["commits"])
        db.update_repository_sync_state(
            repo["id"], "current", _now(), latest_sha=head_sha,
            last_success_at=_now(), error=None,
        )
        return db.get_change_snapshot(repo["id"])
    except Exception as error:
        detail = getattr(error, "detail", str(error))
        db.update_repository_sync_state(
            repo["id"], "failed", _now(), latest_sha=latest_sha,
            error=str(detail)[:500],
        )
        logger.exception("Automatic repository sync failed for %s", repo["id"])
        raise
    finally:
        lock.release()
