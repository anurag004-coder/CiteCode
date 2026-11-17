import logging
import difflib
import re
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .auth import authenticate_demo, clear_session_cookie, get_current_user, set_session_cookie
from .answering import answer_question
from .config import FRONTEND_ORIGINS, GITHUB_WRITE_TOKEN, OPENAI_API_KEY, REPOSITORY_SYNC_INTERVAL_MINUTES
from .benchmark import evaluate_repository
from .github import GitHubClient
from .indexer import index_repository
from .issue_matching import recommend_issues
from .impact import analyze_repository
from .github_actions import action_payload_hash
from .llm import generate_code_fix
from .mcp_client import call_approved_github_action
from .onboarding import build_guide
from .retrieval import build_search_corpus, search
from .repository_sync import refresh_repository
from .sandbox import validate_patch_in_sandbox
from .schemas import (
    AskRequest,
    AskResponse,
    ChangeRefreshRequest,
    ChangeSummaryResponse,
    LoginRequest,
    HealthResponse,
    GuideRequest,
    GuideResponse,
    IssueMatchesResponse,
    IssueRefreshRequest,
    IssueRefreshResponse,
    IndexRequest,
    IndexResponse,
    OnboardingSetupRequest,
    GitHubActionApprovalRequest,
    GitHubActionProposalRequest,
    CodeFixProposalRequest,
    BenchmarkDatasetCreateRequest,
    RetrievalBenchmarkRequest,
    RepositorySummary,
    UserResponse,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("codebase_whisperer")


async def _repository_sync_scheduler():
    interval = max(1, REPOSITORY_SYNC_INTERVAL_MINUTES) * 60
    while True:
        try:
            repositories = await asyncio.to_thread(db.list_repositories)
            for repository in repositories:
                try:
                    await asyncio.to_thread(refresh_repository, repository["id"], "English")
                except HTTPException as error:
                    logger.warning("Scheduled sync failed for %s: %s", repository["id"], error.detail)
                except Exception:
                    logger.exception("Scheduled sync failed for %s", repository["id"])
        except Exception:
            logger.exception("Could not enumerate repositories for scheduled sync")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.initialize()
    sync_task = None
    if REPOSITORY_SYNC_INTERVAL_MINUTES > 0:
        sync_task = asyncio.create_task(_repository_sync_scheduler())
    try:
        yield
    finally:
        if sync_task:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Codebase Whisperer API",
    description="Index public GitHub code and issues, answer with source citations, and match contribution opportunities.",
    version="0.3.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "openai_configured": bool(OPENAI_API_KEY)}


@app.post("/auth/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response):
    user = authenticate_demo(payload.email, payload.password)
    set_session_cookie(response, user["id"])
    return user


@app.post("/auth/logout")
def logout(request: Request, response: Response):
    clear_session_cookie(response, request)
    return {"status": "signed_out"}


@app.get("/auth/me", response_model=UserResponse)
def who_am_i(current_user: Dict = Depends(get_current_user)):
    return current_user


@app.post("/auth/onboarding", response_model=UserResponse)
def save_user_onboarding(
    payload: OnboardingSetupRequest,
    current_user: Dict = Depends(get_current_user),
):
    return db.save_onboarding(
        current_user["id"],
        payload.experience_level,
        payload.goal,
        payload.languages_known,
        payload.setup_os,
        payload.uses_docker,
        payload.time_available,
        payload.explanation_language,
    )


@app.get("/repositories", response_model=List[RepositorySummary])
def repositories(current_user: Dict = Depends(get_current_user)):
    return db.list_repositories()


@app.get("/repositories/{owner}/{name}", response_model=RepositorySummary)
def repository(owner: str, name: str, current_user: Dict = Depends(get_current_user)):
    row = db.get_repository((owner + "/" + name).lower())
    if row is None:
        raise HTTPException(status_code=404, detail="Repository has not been indexed.")
    return row


@app.get("/impact")
def repository_impact(
    repo_id: str = Query(min_length=3, max_length=300),
    path: Optional[str] = Query(default=None, max_length=1000),
    symbol: Optional[str] = Query(default=None, max_length=300),
    start_line: Optional[int] = Query(default=None, ge=1),
    current_user: Dict = Depends(get_current_user),
):
    repo = db.get_repository(repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed.")
    return analyze_repository(
        repo, db.get_indexed_files(repo["id"]), path=path,
        symbol=symbol, start_line=start_line,
    )


@app.post("/index", response_model=IndexResponse)
def index(request: IndexRequest, current_user: Dict = Depends(get_current_user)):
    try:
        return index_repository(request.repository_url)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Repository indexing failed")
        raise HTTPException(status_code=500, detail="Indexing failed. Check backend logs and try again.")


@app.get("/issues", response_model=IssueMatchesResponse)
def issues(
    repo_id: str = Query(min_length=3, max_length=300),
    limit: int = Query(default=12, ge=1, le=30),
    current_user: Dict = Depends(get_current_user),
):
    repo = db.get_repository(repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed.")
    sync = db.get_issue_sync(repo["id"])
    issue_rows = db.list_repository_issues(repo["id"])
    note_parts = []
    if current_user.get("onboarding_goal") == "review_prs":
        note_parts.append("Your saved goal is to review pull requests. This page currently recommends open issues; PR review matching is a separate upcoming feature.")
    if sync is None:
        recommendations = []
        note_parts.append("No open issue snapshot exists yet. Refresh issues for this repository.")
    else:
        recommendations = recommend_issues(
            repo,
            db.get_chunks(repo["id"]),
            issue_rows,
            current_user,
            limit,
        )
        if not recommendations and issue_rows:
            note_parts.append("Open issues were found, but none had enough overlap with indexed source to recommend.")
        elif not issue_rows:
            note_parts.append("No open issues were found in the latest GitHub snapshot.")
    return {
        "repo_id": repo["id"],
        "repository": repo["full_name"],
        "commit_sha": repo["commit_sha"],
        "issue_count": int(repo.get("issue_count", len(issue_rows))),
        "synced_at": sync.get("synced_at") if sync else None,
        "recommendations": recommendations,
        "note": " ".join(note_parts) or None,
    }


@app.post("/issues/refresh", response_model=IssueRefreshResponse)
def refresh_issues(
    payload: IssueRefreshRequest,
    current_user: Dict = Depends(get_current_user),
):
    repo = db.get_repository(payload.repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed.")
    issues = GitHubClient().fetch_open_issues(repo["owner"], repo["name"])
    synced_at = datetime.now(timezone.utc).isoformat()
    db.save_issues(repo["id"], issues, synced_at)
    return {"repo_id": repo["id"], "issue_count": len(issues), "synced_at": synced_at}


def _change_response(repo: Dict, snapshot: Dict = None) -> Dict:
    recent_commits = db.list_recent_commits(repo["id"], 15)
    if not snapshot:
        return {
            "repo_id": repo["id"],
            "repository": repo["full_name"],
            "current_snapshot_sha": repo["commit_sha"],
            "mode": "none",
            "summary": "No change comparison has been saved yet. Refresh this repository to compare it with GitHub.",
            "verification_note": "The repository snapshot is pinned, but no newer commit has been compared yet.",
            "commits": [],
            "recent_commits": recent_commits,
            "files": [],
            "gaps": [],
        }
    gaps = snapshot["gaps"]
    verification_note = snapshot["verification_note"]
    if snapshot["head_sha"] != repo["commit_sha"]:
        gaps = list(gaps) + ["The saved comparison head differs from the currently indexed snapshot."]
    return {
        "repo_id": repo["id"],
        "repository": repo["full_name"],
        "current_snapshot_sha": repo["commit_sha"],
        "base_commit_sha": snapshot["base_sha"],
        "compared_head_sha": snapshot["head_sha"],
        "synced_at": snapshot["synced_at"],
        "last_checked_at": snapshot["checked_at"],
        "mode": snapshot["mode"],
        "summary": snapshot["summary"],
        "verification_note": verification_note,
        "comparison_url": snapshot["comparison_url"] or None,
        "commit_total": snapshot["commit_total"],
        "file_total": snapshot["file_total"],
        "commits": snapshot["commits"],
        "recent_commits": recent_commits,
        "files": snapshot["files"],
        "gaps": gaps,
    }


@app.get("/changes", response_model=ChangeSummaryResponse)
def changes(
    repo_id: str = Query(min_length=3, max_length=300),
    current_user: Dict = Depends(get_current_user),
):
    repo = db.get_repository(repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed.")
    return _change_response(repo, db.get_change_snapshot(repo["id"]))


@app.post("/changes/refresh", response_model=ChangeSummaryResponse)
def refresh_changes(
    payload: ChangeRefreshRequest,
    current_user: Dict = Depends(get_current_user),
):
    repo_id = payload.repo_id.lower()
    snapshot = refresh_repository(
        repo_id, current_user.get("explanation_language", "English")
    )
    repo = db.get_repository(repo_id)
    return _change_response(repo, snapshot)


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, current_user: Dict = Depends(get_current_user)):
    repo = db.get_repository(request.repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed. Call POST /index first.")
    corpus = build_search_corpus(
        repo,
        db.get_chunks(repo["id"]),
        db.list_repository_issues(repo["id"]),
        db.list_recent_commits(repo["id"], 100),
    )
    context_text = "\n".join(
        "{}: {}".format("Earlier question" if message.role == "user" else "Earlier answer", message.content)
        for message in request.context
    )
    contextual_question = request.question
    if context_text:
        contextual_question = "Recent conversation context (not repository evidence):\n{}\n\nCurrent question:\n{}".format(
            context_text, request.question,
        )
    retrieved, sufficient = search(contextual_question, corpus, request.top_k)
    result = answer_question(
        contextual_question,
        repo,
        retrieved,
        sufficient,
        request.explanation_language or current_user.get("explanation_language", "English"),
        source_verifier=_live_source_verifier(repo),
    )
    return {
        "repo_id": repo["id"],
        "repository": repo["full_name"],
        "commit_sha": repo["commit_sha"],
        **result,
    }


def _live_source_verifier(repo: Dict):
    github = GitHubClient()
    live_sources = {}

    def verify_source(item: Dict, quote: Optional[str]) -> bool:
        key = (
            item.get("source_type"), item.get("path"), item.get("commit_sha"),
            item.get("issue_number"),
        )
        if key not in live_sources:
            try:
                live_sources[key] = github.fetch_evidence_source(repo["owner"], repo["name"], item)
            except Exception:
                logger.warning("Could not verify an Ask citation against GitHub for %s", repo["id"])
                live_sources[key] = None
        content = live_sources[key]
        if content is None:
            return False
        if quote is None:
            return True
        normalized_quote = re.sub(r"\s+", " ", quote).strip().casefold()
        normalized_content = re.sub(r"\s+", " ", content).strip().casefold()
        return bool(normalized_quote and normalized_quote in normalized_content)

    return verify_source


@app.post("/guide", response_model=GuideResponse)
def guide(request: GuideRequest, current_user: Dict = Depends(get_current_user)):
    repo = db.get_repository(request.repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed. Index one before generating a guide.")
    experience_level = request.experience_level or current_user.get("experience_level") or "beginner"
    goal = (request.goal or current_user.get("onboarding_goal") or "understand_code").strip()
    preferences = {
        "languages_known": current_user.get("languages_known", []),
        "setup_os": current_user.get("setup_os", "linux"),
        "uses_docker": current_user.get("uses_docker", True),
        "time_available": current_user.get("time_available", "1_day"),
        "explanation_language": current_user.get("explanation_language", "English"),
    }
    chunks = db.get_chunks(repo["id"])
    return build_guide(
        repo, chunks, experience_level, goal, preferences,
        source_verifier=_live_source_verifier(repo),
    )


def _action_response(proposal: Dict) -> Dict:
    repo = db.get_repository(proposal["repo_id"])
    return {
        "id": proposal["id"],
        "repository": repo["full_name"] if repo else proposal["repo_id"],
        "repo_id": proposal["repo_id"],
        "action_type": proposal["action_type"],
        "payload": proposal["payload"],
        "payload_hash": proposal["payload_hash"],
        "status": proposal["status"],
        "result": proposal.get("result"),
        "error": proposal.get("error"),
        "created_at": proposal["created_at"],
        "approved_at": proposal.get("approved_at"),
        "completed_at": proposal.get("completed_at"),
        "events": proposal.get("events", []),
    }


@app.get("/actions")
def list_actions(current_user: Dict = Depends(get_current_user)):
    return {
        "github_write_configured": bool(GITHUB_WRITE_TOKEN),
        "proposals": [_action_response(item) for item in db.list_github_proposals(current_user["id"])],
    }


@app.post("/actions")
def prepare_action(payload: GitHubActionProposalRequest, current_user: Dict = Depends(get_current_user)):
    repo = db.get_repository(payload.repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Index this repository before preparing a GitHub action.")
    content = {"title": payload.title, "body": payload.body}
    if payload.action_type == "issue":
        if payload.labels:
            content["labels"] = payload.labels
    else:
        content.update({"head": payload.head, "base": payload.base, "draft": True})
    proposal = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "repo_id": repo["id"],
        "action_type": payload.action_type,
        "payload": content,
        "payload_hash": action_payload_hash(repo["id"], payload.action_type, content),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.create_github_proposal(proposal)
    return {"github_write_configured": bool(GITHUB_WRITE_TOKEN), "proposal": _action_response(db.get_github_proposal(proposal["id"]))}


@app.post("/actions/code-fix")
def prepare_code_fix(payload: CodeFixProposalRequest, current_user: Dict = Depends(get_current_user)):
    repo = db.get_repository(payload.repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Index this repository before preparing a code fix.")

    issue = None
    if payload.issue_number is not None:
        issue = next(
            (item for item in db.list_repository_issues(repo["id"]) if item.get("number") == payload.issue_number),
            None,
        )
        if issue is None:
            raise HTTPException(
                status_code=404,
                detail="That issue is not in the saved snapshot. Refresh repository issues and try again.",
            )

    chunks = [item for item in db.get_chunks(repo["id"]) if item.get("source_type") == "code"]
    if not chunks:
        raise HTTPException(status_code=422, detail="This repository snapshot has no indexed source code to fix.")

    query = payload.task
    if issue:
        query = "{}\nIssue #{}: {}\n{}".format(
            query, issue["number"], issue["title"], issue.get("body", "")
        )
    evidence, sufficient = search(query, chunks, top_k=12)
    if not evidence or not sufficient:
        raise HTTPException(
            status_code=422,
            detail="The indexed code did not provide enough evidence for a safe fix. Add more details or re-index the repository.",
        )

    github = GitHubClient()
    source_files = []
    seen_paths = set()
    total_source_chars = 0
    for item in evidence:
        path = item["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)
        try:
            content = github.fetch_indexed_code_file(
                repo["owner"], repo["name"], repo["commit_sha"], path
            )
        except HTTPException:
            continue
        if len(content) > 24000 or total_source_chars + len(content) > 48000:
            continue
        source_files.append({"path": path, "content": content})
        total_source_chars += len(content)
        if len(source_files) >= 4:
            break
    if not source_files:
        raise HTTPException(
            status_code=422,
            detail="Could not load a small set of complete source files from the indexed commit for review.",
        )

    issue_context = None
    task = payload.task
    if issue:
        issue_context = issue
        task = "{}\n\nUse the linked issue as additional context; do not assume it is correct if the source disagrees.".format(task)
    generated = generate_code_fix(task, issue_context, evidence[:8], source_files)
    if generated is None:
        raise HTTPException(status_code=503, detail="Code-fix generation is unavailable. Configure the OpenAI API key and try again.")
    raw_changes = generated.get("changes") or []
    if not raw_changes:
        raise HTTPException(
            status_code=422,
            detail=str(generated.get("summary") or "The available evidence was not enough to propose a safe code fix.")[:500],
        )
    if len(raw_changes) > 4:
        raise HTTPException(status_code=422, detail="The generated fix changes too many files. Narrow the task and try again.")

    original_by_path = {item["path"]: item["content"] for item in source_files}
    changes = []
    diff_chars = 0
    seen_changes = set()
    for change in raw_changes:
        if not isinstance(change, dict):
            raise HTTPException(status_code=502, detail="The model returned an invalid code-fix proposal.")
        path = str(change.get("path") or "")
        content = change.get("content")
        if path not in original_by_path or path in seen_changes or not isinstance(content, str):
            raise HTTPException(status_code=502, detail="The generated fix included an unreviewed or invalid file path.")
        if len(content) > 150000:
            raise HTTPException(status_code=422, detail="The generated replacement for {} is too large.".format(path))
        original = original_by_path[path]
        if content == original:
            continue
        seen_changes.add(path)
        diff = "\n".join(difflib.unified_diff(
            original.splitlines(), content.splitlines(),
            fromfile="a/" + path, tofile="b/" + path, lineterm="",
        ))
        diff_chars += len(diff)
        changes.append({"path": path, "content": content, "reason": str(change.get("reason") or "")[:500], "diff": diff})
    if not changes:
        raise HTTPException(status_code=422, detail="The proposed fix did not change any source files.")
    if diff_chars > 80000:
        raise HTTPException(status_code=422, detail="The generated patch is too large to review safely. Narrow the task and try again.")

    proposal_id = str(uuid.uuid4())
    slug = re.sub(r"[^a-z0-9]+", "-", payload.title.lower()).strip("-")[:56] or "bug-fix"
    branch = "codex/fixes/{}-{}".format(slug, proposal_id[:8])
    pr_body = str(generated.get("pr_body") or generated.get("summary") or payload.task).strip()[:10000]
    validation_steps = generated.get("validation_steps") or []
    if isinstance(validation_steps, str):
        validation_steps = [validation_steps]
    if not isinstance(validation_steps, list):
        validation_steps = []
    validation_steps = [str(item).strip()[:300] for item in validation_steps[:8] if str(item).strip()]
    validation = validate_patch_in_sandbox(
        repo["owner"], repo["name"], repo["commit_sha"], changes
    )
    if issue:
        pr_body += "\n\nFixes #{}".format(issue["number"])
    pr_body += "\n\nPrepared from indexed commit `{}`. Sandbox validation: **{}** — {}".format(
        repo["commit_sha"], validation["status"].replace("_", " "), validation["message"]
    )
    if validation_steps:
        pr_body += "\n\nSuggested validation:\n" + "\n".join("- " + item for item in validation_steps)

    action_payload = {
        "title": payload.title,
        "body": pr_body,
        "base_branch": repo["default_branch"],
        "base_sha": repo["commit_sha"],
        "branch": branch,
        "summary": str(generated.get("summary") or "")[:2000],
        "changes": changes,
        "validation_steps": validation_steps,
        "validation": validation,
        "issue_number": issue.get("number") if issue else None,
    }
    proposal = {
        "id": proposal_id,
        "user_id": current_user["id"],
        "repo_id": repo["id"],
        "action_type": "code_pr",
        "payload": action_payload,
        "payload_hash": action_payload_hash(repo["id"], "code_pr", action_payload),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.create_github_proposal(proposal)
    return {
        "github_write_configured": bool(GITHUB_WRITE_TOKEN),
        "proposal": _action_response(db.get_github_proposal(proposal_id)),
    }


@app.post("/actions/{proposal_id}/approve")
def approve_action(
    proposal_id: str,
    payload: GitHubActionApprovalRequest,
    current_user: Dict = Depends(get_current_user),
):
    proposal = db.get_github_proposal(proposal_id)
    if not proposal or proposal["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Action proposal was not found.")
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit approval is required before a GitHub write.")
    if proposal["payload_hash"] != payload.payload_hash or action_payload_hash(
        proposal["repo_id"], proposal["action_type"], proposal["payload"]
    ) != payload.payload_hash:
        raise HTTPException(status_code=409, detail="The proposal changed after review. Prepare and review it again.")
    if not GITHUB_WRITE_TOKEN:
        raise HTTPException(status_code=503, detail="GitHub writes are disabled. Configure GITHUB_WRITE_TOKEN, then approve this proposal.")
    if proposal["status"] not in {"pending", "approved"}:
        raise HTTPException(status_code=409, detail="This proposal has already been rejected or executed.")
    db.approve_github_proposal(
        proposal_id, current_user["id"], payload.payload_hash, datetime.now(timezone.utc).isoformat()
    )
    try:
        call_approved_github_action(proposal_id, payload.payload_hash)
    except RuntimeError as error:
        logger.exception("Approved MCP action failed")
        current = db.get_github_proposal(proposal_id)
        detail = current.get("error") if current and current.get("error") else str(error)
        raise HTTPException(status_code=502, detail=detail)
    return _action_response(db.get_github_proposal(proposal_id))


@app.post("/actions/{proposal_id}/reject")
def reject_action(proposal_id: str, current_user: Dict = Depends(get_current_user)):
    proposal = db.get_github_proposal(proposal_id)
    if not proposal or proposal["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Action proposal was not found.")
    db.reject_github_proposal(proposal_id, current_user["id"], datetime.now(timezone.utc).isoformat())
    return _action_response(db.get_github_proposal(proposal_id))


@app.post("/evaluation/retrieval")
def retrieval_evaluation(
    payload: RetrievalBenchmarkRequest,
    current_user: Dict = Depends(get_current_user),
):
    repo = db.get_repository(payload.repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed.")
    if payload.benchmark_id:
        dataset = db.get_benchmark_set(payload.benchmark_id, current_user["id"], repo["id"])
        if dataset is None:
            raise HTTPException(status_code=404, detail="That benchmark set was not found for this repository.")
        try:
            return evaluate_repository(
                repo,
                db.get_chunks(repo["id"]),
                payload.top_k,
                dataset=dataset,
                issues=db.list_repository_issues(repo["id"]),
                commits=db.list_recent_commits(repo["id"], 100),
                include_answer_quality=payload.include_answer_quality,
                source_verifier=_live_source_verifier(repo) if payload.include_answer_quality else None,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
    try:
        return evaluate_repository(
            repo, db.get_chunks(repo["id"]), payload.top_k,
            include_answer_quality=payload.include_answer_quality,
            source_verifier=_live_source_verifier(repo) if payload.include_answer_quality else None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/evaluation/datasets")
def evaluation_datasets(
    repo_id: str = Query(min_length=3, max_length=300),
    current_user: Dict = Depends(get_current_user),
):
    repo = db.get_repository(repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed.")
    return {"repo_id": repo["id"], "datasets": db.list_benchmark_sets(current_user["id"], repo["id"])}


@app.post("/evaluation/datasets")
def create_evaluation_dataset(
    payload: BenchmarkDatasetCreateRequest,
    current_user: Dict = Depends(get_current_user),
):
    repo = db.get_repository(payload.repo_id.lower())
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository is not indexed.")
    available_refs = {item["path"] for item in db.get_chunks(repo["id"])}
    available_refs.update(
        "issue:{}".format(item["number"]) for item in db.list_repository_issues(repo["id"])
    )
    available_refs.update(
        "commit:{}".format(item["sha"]) for item in db.list_recent_commits(repo["id"], 100)
    )

    normalized_cases = []
    for case in payload.cases:
        normalized_refs = []
        for reference in case.expected_refs:
            candidate = reference
            if reference.lower().startswith("issue:"):
                candidate = "issue:{}".format(reference.split(":", 1)[1].strip().lstrip("#"))
            elif reference.lower().startswith("commit:"):
                requested_sha = reference.split(":", 1)[1].strip().lower()
                matches = [
                    stored for stored in available_refs
                    if stored.startswith("commit:") and stored.split(":", 1)[1].lower().startswith(requested_sha)
                ]
                if len(matches) == 1:
                    candidate = matches[0]
            if candidate not in available_refs:
                raise HTTPException(
                    status_code=422,
                    detail="Unknown expected reference '{}'. Use an indexed file path, issue:number, or commit:sha.".format(reference),
                )
            normalized_refs.append(candidate)
        normalized_cases.append({
            "question": case.question,
            "expected_refs": list(dict.fromkeys(normalized_refs)),
            "answerable": case.answerable,
        })

    now = datetime.now(timezone.utc).isoformat()
    dataset = db.create_benchmark_set({
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "repo_id": repo["id"],
        "name": payload.name,
        "created_at": now,
        "updated_at": now,
        "cases": normalized_cases,
    })
    return dataset
