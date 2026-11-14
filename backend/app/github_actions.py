import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import HTTPException

from . import db
from .config import GITHUB_WRITE_TOKEN


def _github_json(method: str, path: str, payload: Optional[Dict] = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        "https://api.github.com" + path,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + GITHUB_WRITE_TOKEN,
            "Content-Type": "application/json",
            "User-Agent": "Codebase-Whisperer/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
        value = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(value, (dict, list)):
            raise RuntimeError("GitHub returned an unexpected response.")
        return value
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("message", "GitHub rejected the action.")
        except Exception:
            detail = "GitHub rejected the action (HTTP {}).".format(error.code)
        raise RuntimeError(str(detail)[:500])
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not reach GitHub: {}".format(str(error)[:300]))


def _read_after_write(owner: str, name: str, action_type: str, created: Dict, payload: Dict) -> Dict:
    number = created.get("number")
    if not isinstance(number, int):
        return {
            "number": None,
            "title": created.get("title", payload["title"]),
            "html_url": created.get("html_url", ""),
            "state": created.get("state", "open"),
            "draft": bool(created.get("draft", action_type != "issue")),
            "read_after_write_verified": False,
            "verification_detail": "GitHub did not return a record number for a follow-up read.",
        }
    root = "/repos/{}/{}/".format(quote(owner, safe=""), quote(name, safe=""))
    resource = "issues" if action_type == "issue" else "pulls"
    try:
        saved = _github_json("GET", root + resource + "/{}".format(number))
        if not isinstance(saved, dict):
            raise RuntimeError("GitHub returned an unexpected read-after-write response.")
        matches = saved.get("title") == payload.get("title") and saved.get("body", "") == payload.get("body", "")
        if action_type == "issue" and payload.get("labels"):
            actual_labels = {item.get("name") for item in saved.get("labels", []) if isinstance(item, dict)}
            matches = matches and set(payload["labels"]).issubset(actual_labels)
        if action_type in {"draft_pr", "code_pr"}:
            head = (saved.get("head") or {}).get("ref")
            base = (saved.get("base") or {}).get("ref")
            expected_head = payload.get("head") or payload.get("branch")
            expected_base = payload.get("base") or payload.get("base_branch")
            matches = matches and head == expected_head and base == expected_base and bool(saved.get("draft"))
        verified = bool(matches and saved.get("html_url") and saved.get("state") == "open")
        detail = "GitHub returned the saved record and its reviewed fields matched." if verified else "GitHub returned the record, but one or more reviewed fields did not match."
        return {
            "number": saved.get("number", number),
            "title": saved.get("title", created.get("title", payload["title"])),
            "html_url": saved.get("html_url", created.get("html_url", "")),
            "state": saved.get("state", "open"),
            "draft": bool(saved.get("draft", action_type != "issue")),
            "read_after_write_verified": verified,
            "verification_detail": detail,
        }
    except Exception as error:
        return {
            "number": number,
            "title": created.get("title", payload["title"]),
            "html_url": created.get("html_url", ""),
            "state": created.get("state", "open"),
            "draft": bool(created.get("draft", action_type != "issue")),
            "read_after_write_verified": False,
            "verification_detail": "GitHub accepted the write, but the follow-up read failed: {}".format(str(error)[:250]),
        }


def _find_pull_request(owner: str, name: str, branch: str, base_branch: str, title: str) -> Optional[Dict]:
    root = "/repos/{}/{}/pulls?state=all&head={}&per_page=100".format(
        quote(owner, safe=""), quote(name, safe=""), quote(owner + ":" + branch, safe="")
    )
    rows = _github_json("GET", root)
    if not isinstance(rows, list):
        raise RuntimeError("GitHub returned an unexpected pull request search response.")
    for row in rows:
        if (
            isinstance(row, dict)
            and (row.get("head") or {}).get("ref") == branch
            and (row.get("base") or {}).get("ref") == base_branch
            and row.get("title") == title
        ):
            return row
    return None


def _delete_code_branch(owner: str, name: str, branch: str) -> None:
    root = "/repos/{}/{}/git/refs/heads/{}".format(
        quote(owner, safe=""), quote(name, safe=""), quote(branch, safe="/")
    )
    _github_json("DELETE", root)


def _create_code_draft_pr(owner: str, name: str, payload: Dict) -> Dict:
    base_branch = payload.get("base_branch", "")
    base_sha = payload.get("base_sha", "")
    branch = payload.get("branch", "")
    changes = payload.get("changes") or []
    if not base_branch or not base_sha or not branch or not changes:
        raise RuntimeError("The reviewed code-fix proposal is incomplete.")
    if not re.fullmatch(r"codex/fixes/[a-z0-9-]{1,80}", branch):
        raise RuntimeError("The proposed branch name is invalid.")
    if len(changes) > 4:
        raise RuntimeError("A code-fix proposal can change at most four files.")

    root = "/repos/{}/{}/".format(quote(owner, safe=""), quote(name, safe=""))
    branch_info = _github_json("GET", root + "branches/" + quote(base_branch, safe=""))
    current_sha = (branch_info.get("commit") or {}).get("sha")
    if current_sha != base_sha:
        raise RuntimeError(
            "The target branch changed after this fix was prepared. Re-index the repository and prepare a fresh proposal."
        )

    commit_info = _github_json("GET", root + "git/commits/" + quote(base_sha, safe=""))
    base_tree_sha = ((commit_info.get("tree") or {}).get("sha"))
    if not base_tree_sha:
        raise RuntimeError("GitHub did not return the target commit tree.")
    tree_info = _github_json("GET", root + "git/trees/{}?recursive=1".format(quote(base_tree_sha, safe="")))
    if tree_info.get("truncated"):
        raise RuntimeError("GitHub returned a truncated file tree, so the proposed change could not be checked safely.")
    modes = {
        item.get("path"): item.get("mode")
        for item in tree_info.get("tree", [])
        if isinstance(item, dict)
    }

    tree_entries = []
    seen_paths = set()
    for change in changes:
        path = str(change.get("path") or "")
        content = change.get("content")
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or path in seen_paths
            or not isinstance(content, str)
        ):
            raise RuntimeError("The reviewed proposal contains an invalid or duplicate file path.")
        seen_paths.add(path)
        mode = modes.get(path)
        if mode not in {"100644", "100755"}:
            raise RuntimeError("{} is no longer a regular file at the approved base commit.".format(path))
        blob = _github_json("POST", root + "git/blobs", {"content": content, "encoding": "utf-8"})
        if not blob.get("sha"):
            raise RuntimeError("GitHub did not return a blob for {}.".format(path))
        tree_entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob["sha"]})

    tree = _github_json("POST", root + "git/trees", {"base_tree": base_tree_sha, "tree": tree_entries})
    if not tree.get("sha"):
        raise RuntimeError("GitHub did not return the new code tree.")
    commit = _github_json("POST", root + "git/commits", {
        "message": "Codebase Whisperer: {}".format(payload["title"])[:250],
        "tree": tree["sha"],
        "parents": [base_sha],
    })
    if not commit.get("sha"):
        raise RuntimeError("GitHub did not return the code-fix commit.")

    _github_json("POST", root + "git/refs", {
        "ref": "refs/heads/" + branch,
        "sha": commit["sha"],
    })
    try:
        saved_commit = _github_json("GET", root + "git/commits/{}".format(quote(commit["sha"], safe="")))
        saved_ref = _github_json(
            "GET", root + "git/ref/heads/{}".format(quote(branch, safe="/"))
        )
        saved_ref_sha = ((saved_ref.get("object") or {}).get("sha")) if isinstance(saved_ref, dict) else None
        if saved_commit.get("sha") != commit["sha"] or saved_ref_sha != commit["sha"]:
            raise RuntimeError("GitHub did not return the reviewed commit at the created branch.")
    except Exception as error:
        try:
            _delete_code_branch(owner, name, branch)
        except Exception as cleanup_error:
            raise RuntimeError(
                "The code branch could not be verified ({}), and cleanup failed: {}".format(
                    str(error)[:180], str(cleanup_error)[:180]
                )
            )
        raise RuntimeError("The code branch failed read-back verification and was removed: {}".format(error))
    try:
        created = _github_json("POST", root + "pulls", {
            "title": payload["title"],
            "body": payload["body"],
            "head": branch,
            "base": base_branch,
            "draft": True,
        })
    except RuntimeError as error:
        try:
            created = _find_pull_request(owner, name, branch, base_branch, payload["title"])
        except Exception as lookup_error:
            raise RuntimeError(
                "GitHub could not confirm whether the draft PR was created ({}). The code branch {} was preserved for review.".format(
                    str(lookup_error)[:180], branch
                )
            )
        if not created:
            try:
                _delete_code_branch(owner, name, branch)
            except Exception as cleanup_error:
                raise RuntimeError(
                    "GitHub could not open the draft pull request ({}), and cleanup of branch {} failed: {}".format(
                        str(error)[:180], branch, str(cleanup_error)[:180]
                    )
                )
            raise RuntimeError(
                "GitHub could not open the draft pull request, so the temporary code branch was removed: {}".format(error)
            )

    verified = _read_after_write(owner, name, "code_pr", created, payload)
    verified.update({
        "branch": branch,
        "branch_url": "https://github.com/{}/{}/tree/{}".format(owner, name, quote(branch, safe="/")),
        "commit_sha": commit["sha"],
    })
    return verified


def action_payload_hash(repo_id: str, action_type: str, payload: Dict) -> str:
    canonical = json.dumps(
        {"repo_id": repo_id, "action_type": action_type, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execute_approved_action(proposal_id: str, expected_hash: str) -> Dict:
    """Only the MCP tool calls this function; it claims a hash-checked approval first."""
    if not GITHUB_WRITE_TOKEN:
        raise RuntimeError("GitHub writes are disabled. Configure GITHUB_WRITE_TOKEN to execute an approved action.")

    proposal = db.get_github_proposal(proposal_id)
    if not proposal or proposal["payload_hash"] != expected_hash:
        raise RuntimeError("The approved proposal was not found or its review hash changed.")
    if action_payload_hash(proposal["repo_id"], proposal["action_type"], proposal["payload"]) != expected_hash:
        raise RuntimeError("The stored proposal no longer matches its approved review hash.")
    claimed = db.claim_github_proposal(proposal_id, expected_hash)
    if not claimed:
        raise RuntimeError("This proposal is not approved, or it has already been executed.")

    repo = db.get_repository(claimed["repo_id"])
    if not repo:
        db.finish_github_proposal(proposal_id, "failed", _now(), error="The indexed repository was removed.")
        raise RuntimeError("The indexed repository was removed.")

    if claimed["action_type"] not in {"issue", "draft_pr", "code_pr"}:
        db.finish_github_proposal(proposal_id, "failed", _now(), error="Unsupported action type.")
        raise RuntimeError("Unsupported action type.")

    payload = claimed["payload"]
    if claimed["action_type"] == "code_pr":
        try:
            result = _create_code_draft_pr(repo["owner"], repo["name"], payload)
            db.finish_github_proposal(proposal_id, "completed", _now(), result=result)
            return result
        except Exception as error:
            detail = str(error)[:500]
            db.finish_github_proposal(proposal_id, "failed", _now(), error=detail)
            raise RuntimeError(detail)

    path = "/repos/{}/{}/issues".format(repo["owner"], repo["name"])
    body = {"title": payload["title"], "body": payload["body"]}
    if claimed["action_type"] == "issue":
        if payload.get("labels"):
            body["labels"] = payload["labels"]
    elif claimed["action_type"] == "draft_pr":
        path = "/repos/{}/{}/pulls".format(repo["owner"], repo["name"])
        body.update({"head": payload["head"], "base": payload["base"], "draft": True})

    try:
        created = _github_json("POST", path, body)
        result = _read_after_write(repo["owner"], repo["name"], claimed["action_type"], created, payload)
        db.finish_github_proposal(proposal_id, "completed", _now(), result=result)
        return result
    except Exception as error:
        detail = "GitHub action failed: {}".format(str(error)[:300])
        db.finish_github_proposal(proposal_id, "failed", _now(), error=detail)
        raise RuntimeError(detail)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
