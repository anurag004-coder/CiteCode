import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from fastapi import HTTPException

from .config import GITHUB_TOKEN, MAX_FILE_BYTES, MAX_REPO_BYTES, MAX_REPO_FILES


SUPPORTED_CODE = {
    ".py", ".pyw", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".java", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".cxx",
    ".hpp", ".hh", ".cs", ".rb", ".php", ".swift", ".kt", ".kts",
    ".scala", ".sh", ".bash", ".sql", ".vue", ".svelte",
}
SKIP_PARTS = {
    ".git", ".github", ".vscode", "node_modules", "vendor", "dist",
    "build", "target", "coverage", ".venv", "venv", "__pycache__",
    "site-packages", "Pods", "bin", "obj",
}
SKIP_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "Gemfile.lock", "composer.lock", "Pipfile.lock",
}


def parse_github_url(repository_url: str) -> Tuple[str, str]:
    parsed = urlsplit(repository_url.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise HTTPException(status_code=422, detail="Use an https://github.com/owner/repository URL.")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise HTTPException(status_code=422, detail="The URL must point to one GitHub repository.")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    safe = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe.match(owner) or not safe.match(name) or owner in {".", ".."} or name in {".", ".."}:
        raise HTTPException(status_code=422, detail="The repository URL contains an invalid owner or name.")
    return owner, name


class GitHubClient:
    """Small read-only GitHub client. Hosts are fixed to GitHub to avoid SSRF."""

    def __init__(self):
        self.api_root = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Codebase-Whisperer/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if GITHUB_TOKEN:
            self.headers["Authorization"] = "Bearer " + GITHUB_TOKEN

    def _json(self, url: str) -> Any:
        request = Request(url, headers=self.headers)
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                raise HTTPException(status_code=404, detail="GitHub repository, commit, or resource was not found.")
            if error.code == 403:
                raise HTTPException(
                    status_code=429,
                    detail="GitHub rate limit reached. Add a read-only GITHUB_TOKEN and retry.",
                )
            if error.code == 409:
                raise HTTPException(
                    status_code=422,
                    detail="This GitHub repository has no initial commit yet. Push source files, then try again.",
                )
            raise HTTPException(status_code=502, detail="GitHub could not return repository metadata.")
        except (URLError, TimeoutError, json.JSONDecodeError):
            raise HTTPException(status_code=502, detail="Could not reach GitHub. Try again later.")

    def _raw(self, owner: str, name: str, commit_sha: str, path: str) -> bytes:
        encoded_path = quote(path, safe="/")
        url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
            quote(owner, safe=""), quote(name, safe=""), quote(commit_sha, safe=""), encoded_path
        )
        request = Request(url, headers={"User-Agent": self.headers["User-Agent"]})
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read(MAX_FILE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError):
            return b""
        return body if len(body) <= MAX_FILE_BYTES else b""

    def fetch_indexed_code_file(self, owner: str, name: str, commit_sha: str, path: str) -> str:
        """Read one supported source file from the exact commit used by the index."""
        suffix = os.path.splitext(path)[1].lower()
        if not self._keep_path(path) or suffix not in SUPPORTED_CODE:
            raise HTTPException(status_code=422, detail="Code fixes can only use indexed source files.")
        body = self._raw(owner, name, commit_sha, path)
        if not body:
            raise HTTPException(status_code=422, detail="Could not read {} from the indexed commit.".format(path))
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="{} is not UTF-8 source text.".format(path))

    def fetch_evidence_source(self, owner: str, name: str, evidence: Dict) -> Optional[str]:
        """Fetch the cited file lines or GitHub record from the referenced commit/record."""
        source_type = evidence.get("source_type")
        if source_type == "issue":
            issue_number = evidence.get("issue_number")
            if not isinstance(issue_number, int):
                return None
            url = "{}/repos/{}/{}/issues/{}".format(
                self.api_root, quote(owner, safe=""), quote(name, safe=""), issue_number
            )
            record = self._json(url)
            return "{}\n{}".format(record.get("title") or "", record.get("body") or "")

        if source_type == "commit":
            commit_sha = str(evidence.get("commit_sha") or "")
            if not commit_sha:
                return None
            url = "{}/repos/{}/{}/commits/{}".format(
                self.api_root, quote(owner, safe=""), quote(name, safe=""), quote(commit_sha, safe="")
            )
            record = self._json(url)
            return str((record.get("commit") or {}).get("message") or "")

        path = str(evidence.get("path") or "")
        commit_sha = str(evidence.get("commit_sha") or "")
        start_line = evidence.get("start_line")
        end_line = evidence.get("end_line")
        if (
            not path or not commit_sha or not isinstance(start_line, int)
            or not isinstance(end_line, int) or start_line < 1 or end_line < start_line
            or not self._keep_path(path)
        ):
            return None
        body = self._raw(owner, name, commit_sha, path)
        if not body:
            return None
        try:
            lines = body.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return None
        if end_line > len(lines):
            return None
        return "\n".join(lines[start_line - 1 : end_line])

    def index(self, owner: str, name: str, reusable_files: Optional[Dict[str, Dict]] = None) -> Dict:
        reusable_files = reusable_files or {}
        base = "{}/repos/{}/{}".format(self.api_root, quote(owner, safe=""), quote(name, safe=""))
        metadata = self._json(base)
        if metadata.get("private"):
            raise HTTPException(status_code=422, detail="The first version indexes public repositories only.")

        branch = metadata.get("default_branch") or "main"
        commit = self._json(base + "/commits/" + quote(branch, safe=""))
        commit_sha = commit.get("sha")
        if not commit_sha:
            raise HTTPException(status_code=502, detail="GitHub did not return a commit SHA.")

        tree = self._json(base + "/git/trees/" + quote(commit_sha, safe="") + "?recursive=1")
        entries = tree.get("tree", [])
        if tree.get("truncated"):
            entries = self._walk_tree(base, tree.get("sha") or commit_sha)

        candidates = []
        skipped = 0
        declared_bytes = 0
        for entry in entries:
            path = entry.get("path", "")
            if entry.get("type") != "blob" or entry.get("mode") == "120000" or not self._keep_path(path):
                continue
            size = int(entry.get("size") or 0)
            if size > MAX_FILE_BYTES:
                skipped += 1
                continue
            if len(candidates) >= MAX_REPO_FILES or declared_bytes + size > MAX_REPO_BYTES:
                skipped += 1
                continue
            declared_bytes += size
            candidates.append({"path": path, "size": size, "blob_sha": str(entry.get("sha") or "")})

        contents = {}
        file_blob_shas = {}
        download_failures = []
        total_bytes = 0
        pending_downloads = []
        for item in candidates:
            cached = reusable_files.get(item["path"])
            if cached and cached.get("blob_sha") == item["blob_sha"] and isinstance(cached.get("content"), str):
                content = cached["content"]
                size = len(content.encode("utf-8"))
                if total_bytes + size > MAX_REPO_BYTES:
                    skipped += 1
                    continue
                contents[item["path"]] = content
                file_blob_shas[item["path"]] = item["blob_sha"]
                total_bytes += size
            else:
                pending_downloads.append(item)
        workers = min(8, max(1, len(candidates)))
        blob_shas_by_path = {item["path"]: item["blob_sha"] for item in pending_downloads}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._raw, owner, name, commit_sha, item["path"]): item["path"]
                for item in pending_downloads
            }
            for future in as_completed(futures):
                path = futures[future]
                try:
                    body = future.result()
                except Exception:
                    body = b""
                if not body:
                    download_failures.append(path)
                    skipped += 1
                    continue
                if total_bytes + len(body) > MAX_REPO_BYTES:
                    skipped += 1
                    continue
                total_bytes += len(body)
                try:
                    contents[path] = body.decode("utf-8")
                    file_blob_shas[path] = blob_shas_by_path[path]
                except UnicodeDecodeError:
                    skipped += 1

        return {
            "owner": owner,
            "name": name,
            "full_name": metadata.get("full_name", owner + "/" + name),
            "url": metadata.get("html_url", "https://github.com/{}/{}".format(owner, name)),
            "default_branch": branch,
            "commit_sha": commit_sha,
            "files": contents,
            "file_blob_shas": file_blob_shas,
            "download_failures": download_failures,
            "skipped_files": skipped,
        }

    def fetch_open_issues(self, owner: str, name: str, limit: int = 200) -> List[Dict]:
        """Fetch a bounded snapshot of open issues; pull requests are excluded."""
        base = "{}/repos/{}/{}/issues".format(
            self.api_root, quote(owner, safe=""), quote(name, safe="")
        )
        issues = []
        page_size = 100
        page_budget = (limit + page_size - 1) // page_size + 2
        for page in range(1, page_budget + 1):
            rows = self._json(
                "{}?state=open&per_page={}&page={}&sort=updated&direction=desc".format(
                    base, page_size, page
                )
            )
            if not isinstance(rows, list):
                raise HTTPException(status_code=502, detail="GitHub returned an unexpected issue response.")
            for row in rows:
                if not isinstance(row, dict) or "pull_request" in row:
                    continue
                number = row.get("number")
                title = str(row.get("title") or "").strip()
                if not isinstance(number, int) or not title:
                    continue
                labels = [
                    str(label.get("name", ""))[:80]
                    for label in row.get("labels", [])
                    if isinstance(label, dict) and label.get("name")
                ]
                issues.append(
                    {
                        "number": number,
                        "title": title[:500],
                        "body": str(row.get("body") or "")[:12000],
                        "html_url": str(row.get("html_url") or ""),
                        "state": str(row.get("state") or "open"),
                        "labels": labels,
                        "updated_at": str(row.get("updated_at") or ""),
                        "assignee_count": len(row.get("assignees") or []),
                    }
                )
            if len(rows) < page_size or len(issues) >= limit:
                break
        return issues[:limit]

    def latest_branch_head(self, owner: str, name: str) -> Dict:
        base = "{}/repos/{}/{}".format(self.api_root, quote(owner, safe=""), quote(name, safe=""))
        metadata = self._json(base)
        branch = str(metadata.get("default_branch") or "main")
        commit = self._json(base + "/commits/" + quote(branch, safe=""))
        sha = str(commit.get("sha") or "")
        if not sha:
            raise HTTPException(status_code=502, detail="GitHub did not return the latest commit SHA.")
        return {"default_branch": branch, "sha": sha}

    def fetch_recent_commits(self, owner: str, name: str, branch: str, limit: int = 20) -> List[Dict]:
        base = "{}/repos/{}/{}/commits".format(
            self.api_root, quote(owner, safe=""), quote(name, safe="")
        )
        rows = self._json(
            "{}?sha={}&per_page={}".format(base, quote(branch, safe=""), min(max(limit, 1), 100))
        )
        if not isinstance(rows, list):
            raise HTTPException(status_code=502, detail="GitHub returned an unexpected commit history response.")
        result = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("sha"):
                continue
            details = row.get("commit") or {}
            author = details.get("author") or {}
            result.append(
                {
                    "sha": str(row["sha"]),
                    "message": str(details.get("message") or "").strip()[:2000],
                    "author": str(author.get("name") or "Unknown")[:200],
                    "committed_at": str(author.get("date") or ""),
                    "html_url": str(row.get("html_url") or ""),
                }
            )
        return result

    def compare_commits(self, owner: str, name: str, base_sha: str, head_sha: str) -> Dict:
        repo_path = "{}/repos/{}/{}".format(
            self.api_root, quote(owner, safe=""), quote(name, safe="")
        )
        comparison = self._json(
            "{}/compare/{}...{}".format(
                repo_path, quote(base_sha, safe=""), quote(head_sha, safe="")
            )
        )
        if not isinstance(comparison, dict):
            raise HTTPException(status_code=502, detail="GitHub returned an unexpected commit comparison response.")
        commits = []
        raw_commits = comparison.get("commits") or []
        raw_files = comparison.get("files") or []
        for row in raw_commits:
            if not isinstance(row, dict) or not row.get("sha"):
                continue
            details = row.get("commit") or {}
            author = details.get("author") or {}
            commits.append(
                {
                    "sha": str(row.get("sha") or ""),
                    "message": str(details.get("message") or "").strip()[:2000],
                    "author": str(author.get("name") or "Unknown")[:200],
                    "committed_at": str(author.get("date") or ""),
                    "html_url": str(row.get("html_url") or ""),
                }
            )
        files = []
        for row in raw_files:
            if not isinstance(row, dict) or not row.get("filename"):
                continue
            files.append(
                {
                    "path": str(row["filename"])[:1000],
                    "status": str(row.get("status") or "modified")[:40],
                    "additions": int(row.get("additions") or 0),
                    "deletions": int(row.get("deletions") or 0),
                    "changes": int(row.get("changes") or 0),
                    "patch": str(row.get("patch") or "")[:2800],
                    "html_url": str(row.get("blob_url") or ""),
                }
            )
        compare_url = "https://github.com/{}/{}/compare/{}...{}".format(
            quote(owner, safe=""), quote(name, safe=""),
            quote(base_sha, safe=""), quote(head_sha, safe=""),
        )
        return {
            "status": str(comparison.get("status") or "unknown"),
            "ahead_by": int(comparison.get("ahead_by") or 0),
            "total_commits": len(commits),
            "total_files": len(raw_files),
            "commits": commits[:80],
            "files": files[:60],
            "compare_url": compare_url,
        }

    def _walk_tree(self, base: str, root_sha: str) -> List[Dict]:
        """Fallback for GitHub's truncated recursive tree response."""
        pending = [root_sha]
        leaves = []
        visited = 0
        while pending:
            tree_sha = pending.pop()
            result = self._json(base + "/git/trees/" + quote(tree_sha, safe=""))
            visited += 1
            if visited > MAX_REPO_FILES:
                raise HTTPException(status_code=413, detail="Repository has too many directories to index safely.")
            for entry in result.get("tree", []):
                if entry.get("type") == "tree":
                    pending.append(entry.get("sha"))
                elif entry.get("type") == "blob":
                    leaves.append(entry)
                    if len(leaves) > MAX_REPO_FILES * 3:
                        raise HTTPException(status_code=413, detail="Repository tree is too large for this first version.")
        return leaves

    @staticmethod
    def _keep_path(path: str) -> bool:
        pieces = path.split("/")
        if any(piece in SKIP_PARTS or piece.startswith(".") for piece in pieces[:-1]):
            return False
        name = pieces[-1]
        if name in SKIP_NAMES or name.startswith("."):
            return False
        suffix = os.path.splitext(name)[1].lower()
        return suffix in SUPPORTED_CODE or suffix in {".md", ".markdown"}
