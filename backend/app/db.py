import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from .config import DATABASE_PATH, DATA_DIR


SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    default_branch TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    path TEXT NOT NULL,
    symbol TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    commit_sha TEXT NOT NULL,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_repo ON chunks(repo_id);
CREATE INDEX IF NOT EXISTS idx_chunks_repo_path ON chunks(repo_id, path);
CREATE TABLE IF NOT EXISTS repository_files (
    repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    blob_sha TEXT NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (repo_id, path)
);
CREATE TABLE IF NOT EXISTS repository_sync_state (
    repo_id TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'current',
    latest_sha TEXT,
    checked_at TEXT,
    last_success_at TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS repository_issues (
    repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    html_url TEXT NOT NULL,
    state TEXT NOT NULL,
    labels TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    assignee_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (repo_id, number)
);
CREATE INDEX IF NOT EXISTS idx_issues_repo_updated ON repository_issues(repo_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS issue_syncs (
    repo_id TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
    synced_at TEXT NOT NULL,
    issue_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS repository_commits (
    repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    message TEXT NOT NULL,
    author TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    html_url TEXT NOT NULL,
    PRIMARY KEY (repo_id, sha)
);
CREATE INDEX IF NOT EXISTS idx_commits_repo_date ON repository_commits(repo_id, committed_at DESC);
CREATE TABLE IF NOT EXISTS repository_changes (
    repo_id TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
    base_sha TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    mode TEXT NOT NULL,
    verification_note TEXT NOT NULL,
    comparison_url TEXT NOT NULL,
    commit_total INTEGER NOT NULL,
    file_total INTEGER NOT NULL,
    commits TEXT NOT NULL,
    files TEXT NOT NULL,
    gaps TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    experience_level TEXT,
    onboarding_goal TEXT,
    languages_known TEXT NOT NULL DEFAULT '[]',
    setup_os TEXT NOT NULL DEFAULT 'linux',
    uses_docker INTEGER NOT NULL DEFAULT 1,
    time_available TEXT NOT NULL DEFAULT '1_day',
    explanation_language TEXT NOT NULL DEFAULT 'English'
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS github_action_proposals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_github_proposals_user ON github_action_proposals(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS github_action_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL REFERENCES github_action_proposals(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    detail TEXT,
    readback_verified INTEGER,
    readback_detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_github_action_events_proposal ON github_action_events(proposal_id, id);
CREATE TABLE IF NOT EXISTS repository_benchmark_sets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_benchmark_sets_user_repo ON repository_benchmark_sets(user_id, repo_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS repository_benchmark_cases (
    benchmark_id TEXT NOT NULL REFERENCES repository_benchmark_sets(id) ON DELETE CASCADE,
    case_number INTEGER NOT NULL,
    question TEXT NOT NULL,
    expected_refs TEXT NOT NULL,
    answerable INTEGER NOT NULL,
    PRIMARY KEY (benchmark_id, case_number)
);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DATABASE_PATH), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "UPDATE repository_sync_state SET status='stale', error='Sync was interrupted before completion.' WHERE status='syncing'"
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "onboarding_completed" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0"
            )
        if "experience_level" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN experience_level TEXT")
        if "onboarding_goal" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN onboarding_goal TEXT")
        onboarding_columns = {
            "languages_known": "TEXT NOT NULL DEFAULT '[]'",
            "setup_os": "TEXT NOT NULL DEFAULT 'linux'",
            "uses_docker": "INTEGER NOT NULL DEFAULT 1",
            "time_available": "TEXT NOT NULL DEFAULT '1_day'",
            "explanation_language": "TEXT NOT NULL DEFAULT 'English'",
        }
        for column, definition in onboarding_columns.items():
            if column not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN {} {}".format(column, definition))


def _replace_issue_snapshot(connection: sqlite3.Connection, repo_id: str, issues: List[Dict], synced_at: str) -> None:
    connection.execute("DELETE FROM repository_issues WHERE repo_id = ?", (repo_id,))
    if issues:
        connection.executemany(
            """INSERT INTO repository_issues
               (repo_id, number, title, body, html_url, state, labels, updated_at, assignee_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    repo_id,
                    item["number"],
                    item["title"],
                    item.get("body", ""),
                    item["html_url"],
                    item.get("state", "open"),
                    json.dumps(item.get("labels", [])),
                    item.get("updated_at", ""),
                    int(item.get("assignee_count", 0)),
                )
                for item in issues
            ],
        )
    connection.execute(
        """INSERT INTO issue_syncs (repo_id, synced_at, issue_count) VALUES (?, ?, ?)
           ON CONFLICT(repo_id) DO UPDATE SET synced_at=excluded.synced_at, issue_count=excluded.issue_count""",
        (repo_id, synced_at, len(issues)),
    )


def save_index(
    repository: Dict,
    chunks: Iterable[Dict],
    issues: Optional[List[Dict]] = None,
    files: Optional[Dict[str, Dict]] = None,
) -> None:
    """Replace one repository snapshot atomically after indexing succeeds."""
    records = list(chunks)
    with connect() as connection:
        connection.execute(
            """INSERT INTO repositories
               (id, full_name, owner, name, url, default_branch, commit_sha,
                indexed_at, file_count, chunk_count)
               VALUES (:id, :full_name, :owner, :name, :url, :default_branch,
                       :commit_sha, :indexed_at, :file_count, :chunk_count)
               ON CONFLICT(id) DO UPDATE SET
                 full_name=excluded.full_name, owner=excluded.owner,
                 name=excluded.name, url=excluded.url,
                 default_branch=excluded.default_branch,
                 commit_sha=excluded.commit_sha, indexed_at=excluded.indexed_at,
                 file_count=excluded.file_count, chunk_count=excluded.chunk_count""",
            repository,
        )
        connection.execute(
            """INSERT INTO repository_sync_state
               (repo_id, status, latest_sha, checked_at, last_success_at, error)
               VALUES (?, 'current', ?, ?, ?, NULL)
               ON CONFLICT(repo_id) DO UPDATE SET status='current', latest_sha=excluded.latest_sha,
                 checked_at=excluded.checked_at, last_success_at=excluded.last_success_at, error=NULL""",
            (repository["id"], repository["commit_sha"], repository["indexed_at"], repository["indexed_at"]),
        )
        connection.execute("DELETE FROM chunks WHERE repo_id = ?", (repository["id"],))
        connection.executemany(
            """INSERT INTO chunks
               (id, repo_id, source_type, path, symbol, start_line, end_line,
                commit_sha, text, content_hash, embedding)
               VALUES (:id, :repo_id, :source_type, :path, :symbol, :start_line,
                       :end_line, :commit_sha, :text, :content_hash, :embedding)""",
            [
                dict(record, embedding=json.dumps(record["embedding"]) if record["embedding"] else None)
                for record in records
            ],
        )
        if files is not None:
            connection.execute("DELETE FROM repository_files WHERE repo_id = ?", (repository["id"],))
            connection.executemany(
                "INSERT INTO repository_files (repo_id, path, blob_sha, content) VALUES (?, ?, ?, ?)",
                [
                    (repository["id"], path, item["blob_sha"], item["content"])
                    for path, item in files.items()
                ],
            )
        if issues is not None:
            _replace_issue_snapshot(
                connection,
                repository["id"],
                issues,
                repository["indexed_at"],
            )


def get_repository(repo_id: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute(
            """SELECT repositories.*,
                      (SELECT COUNT(*) FROM repository_issues WHERE repo_id = repositories.id) AS issue_count,
                      (SELECT COUNT(*) FROM repository_commits WHERE repo_id = repositories.id) AS commit_count,
                      COALESCE(repository_sync_state.status, 'current') AS sync_status,
                      repository_sync_state.latest_sha AS latest_sha,
                      repository_sync_state.checked_at AS sync_checked_at,
                      repository_sync_state.last_success_at AS last_sync_at,
                      repository_sync_state.error AS sync_error
               FROM repositories LEFT JOIN repository_sync_state ON repository_sync_state.repo_id = repositories.id
               WHERE repositories.id = ?""",
            (repo_id,),
        ).fetchone()
    return dict(row) if row else None


def list_repositories() -> List[Dict]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT repositories.*,
                      (SELECT COUNT(*) FROM repository_issues WHERE repo_id = repositories.id) AS issue_count,
                      (SELECT COUNT(*) FROM repository_commits WHERE repo_id = repositories.id) AS commit_count,
                      COALESCE(repository_sync_state.status, 'current') AS sync_status,
                      repository_sync_state.latest_sha AS latest_sha,
                      repository_sync_state.checked_at AS sync_checked_at,
                      repository_sync_state.last_success_at AS last_sync_at,
                      repository_sync_state.error AS sync_error
               FROM repositories LEFT JOIN repository_sync_state ON repository_sync_state.repo_id = repositories.id
               ORDER BY indexed_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def update_repository_sync_state(
    repo_id: str,
    status: str,
    checked_at: str,
    latest_sha: Optional[str] = None,
    last_success_at: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    with connect() as connection:
        connection.execute(
            """INSERT INTO repository_sync_state
               (repo_id, status, latest_sha, checked_at, last_success_at, error)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(repo_id) DO UPDATE SET status=excluded.status,
                 latest_sha=COALESCE(excluded.latest_sha, repository_sync_state.latest_sha),
                 checked_at=excluded.checked_at,
                 last_success_at=COALESCE(excluded.last_success_at, repository_sync_state.last_success_at),
                 error=excluded.error""",
            (repo_id, status, latest_sha, checked_at, last_success_at, error),
        )


def list_repository_issues(repo_id: str) -> List[Dict]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT number, title, body, html_url, state, labels, updated_at, assignee_count
               FROM repository_issues WHERE repo_id = ? ORDER BY updated_at DESC, number DESC""",
            (repo_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["labels"] = json.loads(item["labels"] or "[]")
        result.append(item)
    return result


def get_issue_sync(repo_id: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute(
            "SELECT synced_at, issue_count FROM issue_syncs WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()
    return dict(row) if row else None


def save_issues(repo_id: str, issues: List[Dict], synced_at: str) -> None:
    with connect() as connection:
        _replace_issue_snapshot(connection, repo_id, issues, synced_at)


def save_commit_history(repo_id: str, commits: List[Dict]) -> None:
    if not commits:
        return
    with connect() as connection:
        connection.executemany(
            """INSERT INTO repository_commits (repo_id, sha, message, author, committed_at, html_url)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(repo_id, sha) DO UPDATE SET message=excluded.message,
                 author=excluded.author, committed_at=excluded.committed_at, html_url=excluded.html_url""",
            [
                (
                    repo_id,
                    item["sha"],
                    item.get("message", "")[:2000],
                    item.get("author", "Unknown")[:200],
                    item.get("committed_at", ""),
                    item.get("html_url", ""),
                )
                for item in commits
            ],
        )
        connection.execute(
            """DELETE FROM repository_commits WHERE repo_id = ? AND sha NOT IN
               (SELECT sha FROM repository_commits WHERE repo_id = ?
                ORDER BY committed_at DESC, sha DESC LIMIT 100)""",
            (repo_id, repo_id),
        )


def list_recent_commits(repo_id: str, limit: int = 20) -> List[Dict]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT sha, message, author, committed_at, html_url
               FROM repository_commits WHERE repo_id = ?
               ORDER BY committed_at DESC, sha DESC LIMIT ?""",
            (repo_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def count_commits(repo_id: str) -> int:
    with connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM repository_commits WHERE repo_id = ?", (repo_id,)
        ).fetchone()
    return int(row["count"]) if row else 0


def save_change_snapshot(repo_id: str, snapshot: Dict) -> None:
    with connect() as connection:
        connection.execute(
            """INSERT INTO repository_changes
               (repo_id, base_sha, head_sha, synced_at, checked_at, summary, mode,
                verification_note, comparison_url, commit_total, file_total, commits, files, gaps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(repo_id) DO UPDATE SET base_sha=excluded.base_sha,
                 head_sha=excluded.head_sha, synced_at=excluded.synced_at,
                 checked_at=excluded.checked_at, summary=excluded.summary, mode=excluded.mode,
                 verification_note=excluded.verification_note, comparison_url=excluded.comparison_url,
                 commit_total=excluded.commit_total, file_total=excluded.file_total,
                 commits=excluded.commits, files=excluded.files, gaps=excluded.gaps""",
            (
                repo_id,
                snapshot["base_sha"],
                snapshot["head_sha"],
                snapshot["synced_at"],
                snapshot["checked_at"],
                snapshot["summary"],
                snapshot["mode"],
                snapshot["verification_note"],
                snapshot["comparison_url"],
                snapshot["commit_total"],
                snapshot["file_total"],
                json.dumps(snapshot.get("commits", [])),
                json.dumps(snapshot.get("files", [])),
                json.dumps(snapshot.get("gaps", [])),
            ),
        )


def get_change_snapshot(repo_id: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM repository_changes WHERE repo_id = ?", (repo_id,)
        ).fetchone()
    if not row:
        return None
    snapshot = dict(row)
    for key in ("commits", "files", "gaps"):
        snapshot[key] = json.loads(snapshot[key] or "[]")
    return snapshot


def mark_changes_checked(repo_id: str, checked_at: str) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE repository_changes SET checked_at = ? WHERE repo_id = ?",
            (checked_at, repo_id),
        )


def get_chunks(repo_id: str) -> List[Dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM chunks WHERE repo_id = ? ORDER BY path, start_line",
            (repo_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["embedding"] = json.loads(item["embedding"]) if item["embedding"] else None
        result.append(item)
    return result


def get_indexed_files(repo_id: str) -> Dict[str, Dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT path, blob_sha, content FROM repository_files WHERE repo_id = ?",
            (repo_id,),
        ).fetchall()
    return {row["path"]: dict(row) for row in rows}


def create_user(user_id: str, email: str, password_hash: str, created_at: str) -> Optional[Dict]:
    try:
        with connect() as connection:
            connection.execute(
                "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, email, password_hash, created_at),
            )
    except sqlite3.IntegrityError:
        return None
    return {
        "id": user_id,
        "email": email,
        "created_at": created_at,
        "onboarding_completed": False,
        "experience_level": None,
        "onboarding_goal": None,
        "languages_known": [],
        "setup_os": "linux",
        "uses_docker": True,
        "time_available": "1_day",
        "explanation_language": "English",
    }


def get_user_by_email(email: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute(
            """SELECT id, email, created_at, onboarding_completed, experience_level, onboarding_goal,
                    languages_known, setup_os, uses_docker, time_available, explanation_language
             FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    user = dict(row)
    user["onboarding_completed"] = bool(user["onboarding_completed"])
    user["languages_known"] = json.loads(user["languages_known"] or "[]")
    user["uses_docker"] = bool(user["uses_docker"])
    return user


def save_onboarding(
    user_id: str,
    experience_level: Optional[str],
    goal: Optional[str],
    languages_known: List[str],
    setup_os: str,
    uses_docker: bool,
    time_available: str,
    explanation_language: str,
) -> Optional[Dict]:
    with connect() as connection:
        connection.execute(
            """UPDATE users SET onboarding_completed=1, experience_level=?, onboarding_goal=?,
                      languages_known=?, setup_os=?, uses_docker=?, time_available=?, explanation_language=?
               WHERE id=?""",
            (experience_level, goal, json.dumps(languages_known), setup_os, int(uses_docker),
             time_available, explanation_language, user_id),
        )
    return get_user_by_id(user_id)


def create_session(token_hash: str, user_id: str, created_at: str, expires_at: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (created_at,))
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, expires_at, created_at),
        )


def get_session_user(token_hash: str, now: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute(
            """SELECT users.id, users.email, users.created_at,
                      users.onboarding_completed, users.experience_level, users.onboarding_goal,
                      users.languages_known, users.setup_os, users.uses_docker,
                      users.time_available, users.explanation_language
               FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (token_hash, now),
        ).fetchone()
    if not row:
        return None
    user = dict(row)
    user["onboarding_completed"] = bool(user["onboarding_completed"])
    user["languages_known"] = json.loads(user["languages_known"] or "[]")
    user["uses_docker"] = bool(user["uses_docker"])
    return user


def delete_session(token_hash: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def create_github_proposal(proposal: Dict) -> None:
    with connect() as connection:
        connection.execute(
            """INSERT INTO github_action_proposals
               (id, user_id, repo_id, action_type, payload_json, payload_hash, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (proposal["id"], proposal["user_id"], proposal["repo_id"], proposal["action_type"],
             json.dumps(proposal["payload"], sort_keys=True, separators=(",", ":")),
             proposal["payload_hash"], proposal["created_at"]),
        )
        _insert_github_action_event(connection, proposal["id"], "proposed", proposal["created_at"])


def _insert_github_action_event(connection, proposal_id: str, event_type: str, occurred_at: str,
                                detail: Optional[str] = None, result: Optional[Dict] = None) -> None:
    result = result or {}
    verified = result.get("read_after_write_verified")
    connection.execute(
        """INSERT INTO github_action_events
           (proposal_id, event_type, occurred_at, detail, readback_verified, readback_detail)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (proposal_id, event_type, occurred_at, detail,
         None if verified is None else int(bool(verified)), result.get("verification_detail")),
    )


def _github_action_events(connection, proposal_id: str) -> List[Dict]:
    rows = connection.execute(
        """SELECT event_type, occurred_at, detail, readback_verified, readback_detail
           FROM github_action_events WHERE proposal_id=? ORDER BY id""",
        (proposal_id,),
    ).fetchall()
    events = [dict(row) for row in rows]
    for event in events:
        if event["readback_verified"] is not None:
            event["readback_verified"] = bool(event["readback_verified"])
    return events


def _decode_github_proposal(row: sqlite3.Row) -> Dict:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
    item.pop("result_json", None)
    return item


def get_github_proposal(proposal_id: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute("SELECT * FROM github_action_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if not row:
            return None
        item = _decode_github_proposal(row)
        item["events"] = _github_action_events(connection, proposal_id)
    return item


def list_github_proposals(user_id: str, limit: int = 50) -> List[Dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM github_action_proposals WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        proposals = [_decode_github_proposal(row) for row in rows]
        for proposal in proposals:
            proposal["events"] = _github_action_events(connection, proposal["id"])
    return proposals


def approve_github_proposal(proposal_id: str, user_id: str, payload_hash: str, approved_at: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE github_action_proposals SET status='approved', approved_at=?
               WHERE id=? AND user_id=? AND status IN ('pending', 'approved') AND payload_hash=?""",
            (approved_at, proposal_id, user_id, payload_hash),
        )
        if cursor.rowcount == 1:
            _insert_github_action_event(connection, proposal_id, "approved", approved_at)
    return cursor.rowcount == 1


def reject_github_proposal(proposal_id: str, user_id: str, completed_at: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE github_action_proposals SET status='rejected', completed_at=?
               WHERE id=? AND user_id=? AND status='pending'""",
            (completed_at, proposal_id, user_id),
        )
        if cursor.rowcount == 1:
            _insert_github_action_event(connection, proposal_id, "rejected", completed_at)
    return cursor.rowcount == 1


def claim_github_proposal(proposal_id: str, payload_hash: str) -> Optional[Dict]:
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE github_action_proposals SET status='executing'
               WHERE id=? AND status='approved' AND payload_hash=?""",
            (proposal_id, payload_hash),
        )
        if cursor.rowcount != 1:
            return None
        _insert_github_action_event(connection, proposal_id, "execution_started", datetime.now(timezone.utc).isoformat())
        row = connection.execute("SELECT * FROM github_action_proposals WHERE id=?", (proposal_id,)).fetchone()
    return _decode_github_proposal(row) if row else None


def finish_github_proposal(proposal_id: str, status: str, completed_at: str,
                           result: Optional[Dict] = None, error: Optional[str] = None) -> None:
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE github_action_proposals SET status=?, completed_at=?, result_json=?, error=?
               WHERE id=? AND status='executing'""",
            (status, completed_at, json.dumps(result) if result else None, error, proposal_id),
        )
        if cursor.rowcount == 1 and status in {"completed", "failed"}:
            detail = error or ("GitHub record saved and read back." if result and result.get("read_after_write_verified") else None)
            _insert_github_action_event(connection, proposal_id, status, completed_at, detail, result)


def create_benchmark_set(dataset: Dict) -> Dict:
    cases = dataset["cases"]
    with connect() as connection:
        connection.execute(
            """INSERT INTO repository_benchmark_sets (id, user_id, repo_id, name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (dataset["id"], dataset["user_id"], dataset["repo_id"], dataset["name"],
             dataset["created_at"], dataset["updated_at"]),
        )
        connection.executemany(
            """INSERT INTO repository_benchmark_cases
               (benchmark_id, case_number, question, expected_refs, answerable)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (dataset["id"], index, item["question"], json.dumps(item["expected_refs"]),
                 int(item["answerable"]))
                for index, item in enumerate(cases, start=1)
            ],
        )
    return {key: dataset[key] for key in ("id", "user_id", "repo_id", "name", "created_at", "updated_at")} | {
        "case_count": len(cases)
    }


def list_benchmark_sets(user_id: str, repo_id: str) -> List[Dict]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT sets.id, sets.name, sets.repo_id, sets.created_at, sets.updated_at,
                      COUNT(cases.case_number) AS case_count
               FROM repository_benchmark_sets AS sets
               LEFT JOIN repository_benchmark_cases AS cases ON cases.benchmark_id = sets.id
               WHERE sets.user_id = ? AND sets.repo_id = ?
               GROUP BY sets.id ORDER BY sets.updated_at DESC""",
            (user_id, repo_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_benchmark_set(benchmark_id: str, user_id: str, repo_id: str) -> Optional[Dict]:
    with connect() as connection:
        row = connection.execute(
            """SELECT id, user_id, repo_id, name, created_at, updated_at
               FROM repository_benchmark_sets WHERE id = ? AND user_id = ? AND repo_id = ?""",
            (benchmark_id, user_id, repo_id),
        ).fetchone()
        if not row:
            return None
        cases = connection.execute(
            """SELECT question, expected_refs, answerable FROM repository_benchmark_cases
               WHERE benchmark_id = ? ORDER BY case_number""",
            (benchmark_id,),
        ).fetchall()
    dataset = dict(row)
    dataset["cases"] = [
        {"id": "custom-{:03d}".format(index), "question": item["question"],
         "expected_refs": json.loads(item["expected_refs"] or "[]"),
         "answerable": bool(item["answerable"])}
        for index, item in enumerate(cases, start=1)
    ]
    return dataset
