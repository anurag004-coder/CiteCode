"""Regression tests for retrieval, verification, refresh, benchmarks, and MCP actions."""
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


TEST_DATA_DIR = tempfile.mkdtemp(prefix="codebase-whisperer-tests-")
os.environ["CODEBASE_DATA_DIR"] = TEST_DATA_DIR
os.environ["REPOSITORY_SYNC_INTERVAL_MINUTES"] = "0"
os.environ["OPENAI_API_KEY"] = ""
os.environ["GITHUB_TOKEN"] = ""
os.environ["GITHUB_WRITE_TOKEN"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app import answering, benchmark, db, github_actions, indexer, main, mcp_client  # noqa: E402
from app.chunking import chunk_file  # noqa: E402
from app.github import GitHubClient  # noqa: E402
from app.repository_sync import refresh_repository  # noqa: E402
from app.retrieval import build_search_corpus, rank_chunks  # noqa: E402


NOW = datetime.now(timezone.utc).isoformat()


def _repository(name):
    return {
        "id": "acme/{}".format(name),
        "full_name": "acme/{}".format(name),
        "owner": "acme",
        "name": name,
        "url": "https://github.com/acme/{}".format(name),
        "default_branch": "main",
        "commit_sha": "base-sha",
        "indexed_at": NOW,
        "file_count": 1,
        "chunk_count": 0,
    }


def _seed_repository(name, files=None, issues=None, commits=None):
    files = files or {"src/auth.py": "def parse_auth_token(token):\n    return 'session validated'\n"}
    repository = _repository(name)
    chunks = []
    file_records = {}
    for path, content in files.items():
        file_records[path] = {
            "blob_sha": "blob-{}".format(path),
            "content": content,
        }
        chunks.extend(
            item.to_record()
            for item in chunk_file(repository["id"], path, repository["commit_sha"], content)
        )
    repository["file_count"] = len(files)
    repository["chunk_count"] = len(chunks)
    db.save_index(repository, chunks, issues=issues or [], files=file_records)
    if commits:
        db.save_commit_history(repository["id"], commits)
    return db.get_repository(repository["id"])


def _issue(number, title, body):
    return {
        "number": number,
        "title": title,
        "body": body,
        "html_url": "https://github.com/acme/retrieval/issues/{}".format(number),
        "state": "open",
        "labels": [],
        "updated_at": NOW,
        "assignee_count": 0,
    }


def _commit(sha, message):
    return {
        "sha": sha,
        "message": message,
        "author": "Test User",
        "committed_at": NOW,
        "html_url": "https://github.com/acme/retrieval/commit/{}".format(sha),
    }


class FeatureRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        response = cls.client.post(
            "/auth/login",
            json={"email": "example123@gmail.com", "password": "Admin@123"},
        )
        if response.status_code != 200:
            raise AssertionError("Demo login failed: {}".format(response.text))
        cls.user = db.get_user_by_email("example123@gmail.com")

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)

    def _live_verifier(self, repo):
        def verify(item, quote):
            if quote is None:
                return True
            return quote.casefold() in answering._evidence_source_text(item).casefold()
        return verify

    def test_health_authentication_and_language_preference(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertFalse(health.json()["openai_configured"])

        unauthorized = TestClient(main.app, raise_server_exceptions=False).get("/repositories")
        self.assertEqual(unauthorized.status_code, 401)

        saved = self.client.post("/auth/onboarding", json={
            "experience_level": "beginner",
            "goal": "understand_code",
            "languages_known": ["Python"],
            "setup_os": "linux",
            "uses_docker": False,
            "time_available": "1_day",
            "explanation_language": "Hindi",
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["explanation_language"], "Hindi")

    def test_ask_requires_live_exact_citation_and_passes_language(self):
        repo = _seed_repository("ask-check")
        languages = []

        def generate(question, evidence, language):
            languages.append(language)
            item = evidence[0]
            return {
                "not_enough_evidence": False,
                "claims": [{
                    "text": "La función valida la sesión.",
                    "label": "FROM_CODE",
                    "evidence_ids": [item["evidence_id"]],
                    "evidence_quote": "return 'session validated'",
                }],
            }

        with patch.object(main, "_live_source_verifier", side_effect=self._live_verifier), \
                patch.object(answering, "generate_claims", side_effect=generate):
            response = self.client.post("/ask", json={
                "repo_id": repo["id"],
                "question": "Where does parse auth token return session validated?",
                "explanation_language": "Spanish",
            })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(languages, ["Spanish"])
        self.assertEqual(body["claims"][0]["status"], "source_checked")
        self.assertEqual(body["claims"][0]["citations"][0]["reference_key"], "src/auth.py")

        with patch.object(main, "_live_source_verifier", side_effect=self._live_verifier), \
                patch.object(answering, "generate_claims", return_value={
                    "not_enough_evidence": False,
                    "claims": [{
                        "text": "Unsupported repository claim.",
                        "label": "FROM_CODE",
                        "evidence_ids": ["E1"],
                        "evidence_quote": "this quote is absent from all source files",
                    }],
                }):
            rejected = self.client.post("/ask", json={
                "repo_id": repo["id"], "question": "Where does parse auth token return?",
            })
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["mode"], "refusal")
        self.assertEqual(rejected.json()["claims"], [])

    def test_issues_commits_and_multilingual_guide_are_retrievable(self):
        issue = _issue(101, "Frobnicator cache miss", "The frobnicator endpoint returns a cache token on a miss.")
        commit = _commit("commit-cache-1", "Document cache invalidation transaction boundaries")
        repo = _seed_repository("retrieval", issues=[issue], commits=[commit])
        chunks = db.get_chunks(repo["id"])
        corpus = build_search_corpus(repo, chunks, db.list_repository_issues(repo["id"]), db.list_recent_commits(repo["id"]))

        issue_hits, _ = rank_chunks("frobnicator endpoint cache miss", corpus, method="keyword")
        commit_hits, _ = rank_chunks("cache invalidation transaction boundaries", corpus, method="keyword")
        self.assertEqual(issue_hits[0]["reference_key"], "issue:101")
        self.assertEqual(commit_hits[0]["reference_key"], "commit:commit-cache-1")

        generated_languages = []
        def make_answer(question, evidence, language):
            generated_languages.append(language)
            item = evidence[0]
            return {"not_enough_evidence": False, "claims": [{
                "text": "Respuesta con fuente.", "label": "FROM_CODE",
                "evidence_ids": [item["evidence_id"]],
                "evidence_quote": answering._evidence_source_text(item)[:80],
            }]}

        with patch.object(main, "_live_source_verifier", side_effect=self._live_verifier), \
                patch.object(answering, "generate_claims", side_effect=make_answer):
            issue_answer = self.client.post("/ask", json={
                "repo_id": repo["id"], "question": "frobnicator endpoint cache miss", "explanation_language": "Spanish",
            })
            commit_answer = self.client.post("/ask", json={
                "repo_id": repo["id"], "question": "cache invalidation transaction boundaries", "explanation_language": "Spanish",
            })
        self.assertEqual(issue_answer.status_code, 200, issue_answer.text)
        self.assertEqual(issue_answer.json()["claims"][0]["citations"][0]["source_type"], "issue")
        self.assertIn("/issues/101", issue_answer.json()["claims"][0]["citations"][0]["url"])
        self.assertEqual(commit_answer.status_code, 200, commit_answer.text)
        self.assertEqual(commit_answer.json()["claims"][0]["citations"][0]["source_type"], "commit")
        self.assertIn("/commit/commit-cache-1", commit_answer.json()["claims"][0]["citations"][0]["url"])
        self.assertEqual(generated_languages, ["Spanish", "Spanish"])

        captured = {}
        def guide_generator(level, goal, preferences, evidence):
            captured["evidence"] = evidence
            return {"title": "Guide", "summary": "Summary", "gaps": [], "sections": [{
                "title": "Authentication",
                "text": "The parser returns a validated session.",
                "label": "FROM_CODE",
                "evidence_ids": [evidence[0]["evidence_id"]],
                "evidence_quote": evidence[0]["text"][:60],
            }]}

        with patch("app.onboarding.generate_onboarding_guide", side_effect=guide_generator), \
                patch.object(main, "_live_source_verifier", side_effect=self._live_verifier):
            guide_repo = _seed_repository("guide", files={
                "README.md": "# Overview\n\nInstall dependencies and run the application to understand the architecture.\n",
                "src/auth.py": "def parse_auth_token(token):\n    return 'session validated'\n",
            })
            guide = self.client.post("/guide", json={"repo_id": guide_repo["id"]})
        self.assertEqual(guide.status_code, 200, guide.text)
        self.assertEqual(guide.json()["sections"][0]["status"], "source_checked")

        with patch("app.onboarding.generate_onboarding_guide", return_value={
            "title": "Guide", "summary": "Summary", "gaps": [], "sections": [{
                "title": "Unsupported", "text": "Unsupported explanation", "label": "FROM_CODE",
                "evidence_ids": [captured["evidence"][0]["evidence_id"]], "evidence_quote": "not in source",
            }],
        }), patch.object(main, "_live_source_verifier", side_effect=self._live_verifier):
            fallback = self.client.post("/guide", json={"repo_id": guide_repo["id"]})
        self.assertEqual(fallback.status_code, 200, fallback.text)
        self.assertEqual(fallback.json()["mode"], "extractive")

    def test_custom_benchmark_dataset_round_trip_and_answer_quality_metrics(self):
        repo = _seed_repository("bench", files={"src/cache.py": "def rebuild_cache():\n    return 'atomic cache transaction'\n"})
        dataset_response = self.client.post("/evaluation/datasets", json={
            "repo_id": repo["id"],
            "name": "Cache accuracy",
            "cases": [
                {"question": "How is the cache rebuilt?", "expected_refs": ["src/cache.py"], "answerable": True},
                {"question": "Where is the moon database stored?", "expected_refs": [], "answerable": False},
            ],
        })
        self.assertEqual(dataset_response.status_code, 200, dataset_response.text)
        benchmark_id = dataset_response.json()["id"]
        listed = self.client.get("/evaluation/datasets", params={"repo_id": repo["id"]})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["datasets"][0]["case_count"], 2)

        def quality_answer(question, repository, retrieved, sufficient, language, source_verifier=None, include_diagnostics=False):
            answerable_case = "cache rebuilt" in question.lower()
            claims = [{"status": "source_checked", "citations": [{"reference_key": "src/cache.py"}]}] if answerable_case else []
            diagnostics = {
                "generation_performed": True,
                "generated_fact_claims": 1,
                "source_checked_fact_claims": 1 if answerable_case else 0,
                "rejected_fact_claims": 0 if answerable_case else 1,
            }
            return {"mode": "generated", "claims": claims, "_quality_diagnostics": diagnostics}

        with patch.object(benchmark, "answer_question", side_effect=quality_answer), \
                patch.object(main, "_live_source_verifier", side_effect=self._live_verifier):
            scored = self.client.post("/evaluation/retrieval", json={
                "repo_id": repo["id"], "benchmark_id": benchmark_id,
                "top_k": 5, "include_answer_quality": True,
            })
        self.assertEqual(scored.status_code, 200, scored.text)
        quality = scored.json()["answer_quality"]
        self.assertEqual(quality["citation_precision"], 1.0)
        self.assertEqual(quality["citation_recall"], 1.0)
        self.assertEqual(quality["source_check_rejection_rate"], 0.5)
        self.assertEqual(quality["unanswerable_hallucination_rate"], 1.0)

        with self.assertRaises(ValueError):
            benchmark.evaluate_repository(
                repo,
                db.get_chunks(repo["id"]),
                dataset={"name": "too many", "cases": [{
                    "id": str(i), "question": "question", "expected_refs": ["src/cache.py"], "answerable": True,
                } for i in range(41)]},
                include_answer_quality=True,
            )

    def test_incremental_index_reuses_unchanged_chunks_and_embeddings(self):
        old_a = "def old_cache():\n    return 'old value'\n"
        kept = "def keep_cache():\n    return 'unchanged cached text'\n"
        repo = _seed_repository("incremental", files={"src/a.py": old_a, "src/b.py": kept})
        old_chunks = db.get_chunks(repo["id"])
        old_b = next(item for item in old_chunks if item["path"] == "src/b.py")
        old_b["embedding"] = [0.2, 0.8]
        db.save_index(repo, old_chunks, issues=[], files={
            "src/a.py": {"blob_sha": "a-old", "content": old_a},
            "src/b.py": {"blob_sha": "b-same", "content": kept},
        })

        class FakeGitHub:
            def index(self, owner, name, reusable_files=None):
                self.reusable_files = reusable_files
                return {
                    "owner": owner, "name": name, "full_name": "acme/incremental",
                    "url": repo["url"], "default_branch": "main", "commit_sha": "new-sha",
                    "files": {
                        "src/a.py": "def new_cache():\n    return 'new value'\n",
                        "src/b.py": kept,
                        "src/c.py": "def added_cache():\n    return 'new file value'\n",
                    },
                    "file_blob_shas": {"src/a.py": "a-new", "src/b.py": "b-same", "src/c.py": "c-new"},
                    "download_failures": [], "skipped_files": 0,
                }
            def fetch_open_issues(self, owner, name):
                return []
            def fetch_recent_commits(self, owner, name, branch):
                return []

        embedded = []
        def fake_embed(texts):
            embedded.extend(texts)
            return [[0.1, 0.9] for _ in texts]

        with patch.object(indexer, "GitHubClient", FakeGitHub), patch.object(indexer, "embed_texts", side_effect=fake_embed):
            result = indexer.index_repository(repo["url"])

        self.assertEqual(result["commit_sha"], "new-sha")
        self.assertEqual(set(db.get_indexed_files(repo["id"])), {"src/a.py", "src/b.py", "src/c.py"})
        refreshed = db.get_chunks(repo["id"])
        new_b = next(item for item in refreshed if item["path"] == "src/b.py")
        self.assertEqual(new_b["id"], old_b["id"])
        self.assertEqual(new_b["commit_sha"], "new-sha")
        self.assertEqual(new_b["embedding"], [0.2, 0.8])
        self.assertEqual(len(embedded), 2)
        self.assertFalse(any("unchanged cached text" in text for text in embedded))

    def test_live_github_source_fetches_issue_commit_and_exact_lines(self):
        client = GitHubClient()
        with patch.object(client, "_json", side_effect=[{"title": "Title", "body": "Issue details here"},
                                                          {"commit": {"message": "Commit message details"}}]), \
                patch.object(client, "_raw", return_value=b"first line\nexact cited source line\nthird line\n"):
            issue = client.fetch_evidence_source("acme", "repo", {"source_type": "issue", "issue_number": 7})
            commit = client.fetch_evidence_source("acme", "repo", {"source_type": "commit", "commit_sha": "sha"})
            source = client.fetch_evidence_source("acme", "repo", {
                "source_type": "code", "path": "src/auth.py", "commit_sha": "sha", "start_line": 2, "end_line": 2,
            })
        self.assertIn("Issue details here", issue)
        self.assertEqual(commit, "Commit message details")
        self.assertEqual(source, "exact cited source line")

    def test_read_after_write_verifies_issue_and_draft_pull_request(self):
        issue_payload = {"title": "Fix cache", "body": "Cache issue details", "labels": ["bug"]}
        with patch.object(github_actions, "_github_json", return_value={
            "number": 12, "title": "Fix cache", "body": "Cache issue details",
            "labels": [{"name": "bug"}], "html_url": "https://github.com/acme/repo/issues/12", "state": "open",
        }) as read:
            issue = github_actions._read_after_write("acme", "repo", "issue", {"number": 12}, issue_payload)
        self.assertTrue(issue["read_after_write_verified"])
        read.assert_called_once_with("GET", "/repos/acme/repo/issues/12")

        pr_payload = {"title": "Draft", "body": "Draft body", "head": "feature", "base": "main"}
        with patch.object(github_actions, "_github_json", return_value={
            "number": 18, "title": "Draft", "body": "Draft body", "head": {"ref": "feature"},
            "base": {"ref": "main"}, "draft": True, "html_url": "https://github.com/acme/repo/pull/18", "state": "open",
        }):
            pr = github_actions._read_after_write("acme", "repo", "draft_pr", {"number": 18}, pr_payload)
        self.assertTrue(pr["read_after_write_verified"])

    def test_approved_issue_write_is_hash_checked_and_read_back(self):
        repo = _seed_repository("issue-action")
        payload = {"title": "Fix the parser", "body": "Parser failure details", "labels": ["bug"]}
        proposal_id = "issue-action-regression"
        payload_hash = github_actions.action_payload_hash(repo["id"], "issue", payload)
        db.create_github_proposal({
            "id": proposal_id,
            "user_id": self.user["id"],
            "repo_id": repo["id"],
            "action_type": "issue",
            "payload": payload,
            "payload_hash": payload_hash,
            "created_at": NOW,
        })
        db.approve_github_proposal(proposal_id, self.user["id"], payload_hash, NOW)
        with patch.object(github_actions, "GITHUB_WRITE_TOKEN", "mock-write-token"), \
                patch.object(github_actions, "_github_json", side_effect=[
                    {"number": 22, "title": payload["title"], "body": payload["body"],
                     "html_url": "https://github.com/acme/issue-action/issues/22", "state": "open"},
                    {"number": 22, "title": payload["title"], "body": payload["body"],
                     "labels": [{"name": "bug"}],
                     "html_url": "https://github.com/acme/issue-action/issues/22", "state": "open"},
                ]) as github_call:
            with self.assertRaisesRegex(RuntimeError, "review hash changed"):
                github_actions.execute_approved_action(proposal_id, "0" * 64)
            self.assertEqual(db.get_github_proposal(proposal_id)["status"], "approved")
            result = github_actions.execute_approved_action(proposal_id, payload_hash)
        self.assertTrue(result["read_after_write_verified"])
        self.assertEqual(db.get_github_proposal(proposal_id)["status"], "completed")
        self.assertEqual(github_call.call_count, 2)

    def test_mcp_client_accepts_structured_success_result(self):
        @asynccontextmanager
        async def fake_stdio(server_parameters):
            yield (object(), object())

        class FakeSession:
            def __init__(self, read_stream, write_stream):
                self.read_stream = read_stream
                self.write_stream = write_stream
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def initialize(self):
                return None
            async def list_tools(self):
                return SimpleNamespace(tools=[SimpleNamespace(name=mcp_client.TOOL_NAME)])
            async def call_tool(self, tool_name, arguments):
                return SimpleNamespace(
                    isError=False,
                    structuredContent={"number": 31, "verified": True},
                    content=[],
                )

        with patch.object(mcp_client, "stdio_client", fake_stdio), \
                patch.object(mcp_client, "ClientSession", FakeSession):
            result = mcp_client.call_approved_github_action("unused", "unused")
        self.assertEqual(result, {"number": 31, "verified": True})

    def test_failed_code_pr_creation_removes_temporary_branch(self):
        payload = {
            "title": "Fix cache", "body": "Reviewed fix", "base_branch": "main", "base_sha": "base",
            "branch": "codex/fixes/cache-fix", "changes": [{"path": "src/cache.py", "content": "replacement"}],
        }
        calls = []
        def fake_github(method, path, body=None):
            calls.append((method, path))
            if method == "GET" and path.endswith("/branches/main"):
                return {"commit": {"sha": "base"}}
            if method == "GET" and path.endswith("/git/commits/base"):
                return {"tree": {"sha": "tree-base"}}
            if method == "GET" and path.endswith("/git/trees/tree-base?recursive=1"):
                return {"tree": [{"path": "src/cache.py", "mode": "100644"}]}
            if method == "POST" and path.endswith("/git/blobs"):
                return {"sha": "blob-new"}
            if method == "POST" and path.endswith("/git/trees"):
                return {"sha": "tree-new"}
            if method == "POST" and path.endswith("/git/commits"):
                return {"sha": "commit-new"}
            if method == "POST" and path.endswith("/git/refs"):
                return {"ref": "refs/heads/codex/fixes/cache-fix"}
            if method == "GET" and path.endswith("/git/commits/commit-new"):
                return {"sha": "commit-new"}
            if method == "GET" and path.endswith("/git/ref/heads/codex/fixes/cache-fix"):
                return {"object": {"sha": "commit-new"}}
            if method == "POST" and path.endswith("/pulls"):
                raise RuntimeError("validation failed")
            if method == "GET" and "/pulls?state=all&head=" in path:
                return []
            if method == "DELETE" and path.endswith("/git/refs/heads/codex/fixes/cache-fix"):
                return {}
            raise AssertionError("Unexpected GitHub request {} {}".format(method, path))

        with patch.object(github_actions, "_github_json", side_effect=fake_github):
            with self.assertRaisesRegex(RuntimeError, "temporary code branch was removed"):
                github_actions._create_code_draft_pr("acme", "repo", payload)
        self.assertIn(("DELETE", "/repos/acme/repo/git/refs/heads/codex/fixes/cache-fix"), calls)

    def test_repository_sync_reports_current_and_failed_status(self):
        current_repo = _seed_repository("sync-current")
        class CurrentGitHub:
            def latest_branch_head(self, owner, name):
                return {"sha": "base-sha", "default_branch": "main"}
            def fetch_recent_commits(self, owner, name, branch):
                return []
            def fetch_open_issues(self, owner, name):
                return []
        with patch("app.repository_sync.GitHubClient", CurrentGitHub):
            refresh_repository(current_repo["id"])
        self.assertEqual(db.get_repository(current_repo["id"])["sync_status"], "current")

        failing_repo = _seed_repository("sync-failed")
        class FailedGitHub:
            def latest_branch_head(self, owner, name):
                raise HTTPException(status_code=502, detail="GitHub unavailable")
        with patch("app.repository_sync.GitHubClient", FailedGitHub), patch("app.repository_sync.logger.exception"):
            with self.assertRaises(HTTPException):
                refresh_repository(failing_repo["id"])
        failed = db.get_repository(failing_repo["id"])
        self.assertEqual(failed["sync_status"], "failed")
        self.assertEqual(failed["sync_error"], "GitHub unavailable")

    def test_repository_sync_refreshes_advanced_branch_and_change_snapshot(self):
        repo = _seed_repository("sync-advanced")
        comparison = {
            "total_commits": 1,
            "total_files": 1,
            "commits": [_commit("head-sha", "Update cache behavior")],
            "files": [{"path": "src/auth.py", "status": "modified", "additions": 1,
                       "deletions": 0, "patch": "+return True"}],
            "compare_url": "https://github.com/acme/sync-advanced/compare/base-sha...head-sha",
            "gaps": [],
        }

        class AdvancedGitHub:
            def latest_branch_head(self, owner, name):
                return {"sha": "head-sha", "default_branch": "main"}
            def compare_commits(self, owner, name, base_sha, head_sha):
                return comparison

        def refresh_snapshot(url):
            current = db.get_repository(repo["id"])
            current["commit_sha"] = "head-sha"
            current["indexed_at"] = datetime.now(timezone.utc).isoformat()
            records = db.get_chunks(repo["id"])
            files = db.get_indexed_files(repo["id"])
            current["file_count"] = len(files)
            current["chunk_count"] = len(records)
            db.save_index(current, records, issues=[], files=files)
            return {"commit_sha": "head-sha", "warning": None}

        with patch("app.repository_sync.GitHubClient", AdvancedGitHub), \
                patch("app.repository_sync.index_repository", side_effect=refresh_snapshot):
            snapshot = refresh_repository(repo["id"])
        self.assertEqual(snapshot["head_sha"], "head-sha")
        refreshed = db.get_repository(repo["id"])
        self.assertEqual(refreshed["commit_sha"], "head-sha")
        self.assertEqual(refreshed["sync_status"], "current")
        self.assertEqual(snapshot["file_total"], 1)

    def test_fastmcp_client_and_server_claim_only_approved_hash(self):
        repo = _seed_repository("mcp")
        payload = {"title": "offline MCP error-path test"}
        proposal_id = "mcp-regression-proposal"
        payload_hash = github_actions.action_payload_hash(repo["id"], "unsupported_test_action", payload)
        db.create_github_proposal({
            "id": proposal_id,
            "user_id": self.user["id"],
            "repo_id": repo["id"],
            "action_type": "unsupported_test_action",
            "payload": payload,
            "payload_hash": payload_hash,
            "created_at": NOW,
        })
        db.approve_github_proposal(proposal_id, self.user["id"], payload_hash, NOW)
        with patch.object(mcp_client, "GITHUB_WRITE_TOKEN", "test-token"):
            with self.assertRaisesRegex(RuntimeError, "Unsupported action type"):
                mcp_client.call_approved_github_action(proposal_id, payload_hash)
        self.assertEqual(db.get_github_proposal(proposal_id)["status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
