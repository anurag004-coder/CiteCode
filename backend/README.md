# Codebase Whisperer backend

This backend supports a fixed local demo sign-in, public GitHub repository snapshots, source and documentation search, citation-backed answers, personalized onboarding, open-issue matching, and scheduled repository sync. Ask searches indexed code and documentation, cached open issues, and recent commits. It uses FastAPI, SQLite, Tree-sitter language grammars, BM25-style keyword search, optional OpenAI embeddings, and optional OpenAI answer generation.

## Run locally

Use Python 3.10 or newer for the official MCP Python SDK and FastMCP action server. Docker Desktop or Docker Engine must also be installed and running for isolated code-fix checks; without Docker, the app records that checks were unavailable and still requires human review. From this directory:

```sh
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in your shell before starting the app if you want embedding search and generated answers. Without a key, the backend still supports keyword search and returns exact source excerpts. The key is only used by the backend and is never returned from an API route.

```sh
uvicorn app.main:app --reload --port 8001
```

Open <http://127.0.0.1:8001/docs> for the interactive API page. The existing static site runs on port 8000; its browser can reach this API through the configured local CORS origins.

## API

- `GET /health` - backend status and whether an OpenAI key is configured.
- `POST /auth/login` - sign in with the prefilled demo credentials (`example123@gmail.com` / `Admin@123`) and start a session. The demo user is created on first sign-in; arbitrary account creation is disabled.
- `POST /auth/logout` - end the current session.
- `GET /auth/me` - return the signed-in account.
- `POST /auth/onboarding` - save first visit preferences: experience, goal, known languages, OS, Docker, time budget, and explanation language; skipping applies the documented defaults.
- `POST /index` - index a public GitHub repository. Example body: `{"repository_url":"https://github.com/owner/repository"}`.
- `GET /issues?repo_id=owner/repository` - rank cached open issues against repository source and the signed-in user's goal, experience, and language profile.
- `POST /issues/refresh` - refresh the cached open-issue snapshot. Example body: `{"repo_id":"owner/repository"}`. At most 200 open issues are stored per repository.
- `GET /changes?repo_id=owner/repository` - return the saved change summary and recent commit history.
- `POST /changes/refresh` - compare the indexed commit to the default branch, refresh code/issues/commit data when it has advanced, and save a change summary. Example body: `{"repo_id":"owner/repository"}`.
- `GET /repositories` - list indexed repository snapshots and automatic sync status (`current`, `stale`, `syncing`, or `failed`).
- `GET /repositories/{owner}/{name}` - show one indexed snapshot.
- `POST /ask` - search source, documentation, issues, and recent commits, then answer with source or GitHub record citations. Example body: `{"repo_id":"owner/repository","question":"Where is authentication checked?","explanation_language":"Hindi"}`. Omit `explanation_language` to use the saved onboarding preference.
- `POST /guide` - create a guide shaped by the saved learner profile and an indexed repository. Generated prose follows the chosen explanation language while paths and citations stay unchanged.
- `GET /actions` - list the signed-in user's GitHub action proposals and whether a write token is configured.
- `POST /actions` - save a proposed issue or draft pull request without contacting GitHub.
- `POST /actions/code-fix` - use indexed source and optional open-issue context to generate a bounded code patch and save it for review; this does not contact GitHub.
- `POST /actions/{proposal_id}/approve` - explicitly approve the matching payload hash and execute it through the local MCP tool; requires `{"confirm":true,"payload_hash":"..."}`.
- `POST /actions/{proposal_id}/reject` - reject an unapproved proposal.
- `GET /evaluation/datasets?repo_id=owner/repository` - list saved question sets for that repository.
- `POST /evaluation/datasets` - save a repository-specific labeled question set. Cases use `question`, `expected_refs`, and `answerable`; references are indexed file paths, `issue:number`, or `commit:sha`. Limit 200 cases per set.
- `POST /evaluation/retrieval` - score the built-in 34-question set, or pass `benchmark_id` to score a saved repository-specific set. Set `include_answer_quality` to `true` to also generate/live-check answers and calculate gold-reference citation and unanswerable-question metrics (maximum 40 cases). Example: `{"repo_id":"owner/repository","top_k":5,"benchmark_id":"...","include_answer_quality":true}`.

Repository sync runs automatically when the backend starts and then every `REPOSITORY_SYNC_INTERVAL_MINUTES` (default 60). Set it to `0` to disable scheduled checks. Each check reads the default branch; when it advances, the backend compares Git blob SHAs, downloads and re-chunks/re-embeds only changed or added supported files, and removes deleted paths from the saved snapshot. Unchanged file contents, chunks, and embeddings are reused with the new commit SHA. A change summary is saved with the refreshed snapshot. The repository list shows the last check and any sync error. Manual refresh remains available through `POST /changes/refresh`.

The index, repository list, and question routes require a demo session. Sessions use random tokens in HTTP-only cookies; only a hash of each token is stored in SQLite. Demo credentials are checked directly by the local-only mock login; there is no password signup or password verification flow. Indexing stores the exact commit SHA. Citations link to that SHA and the checked line range. Re-indexing the same repository replaces its stored snapshot only after the new index has been built successfully.

## Current scope

The current backend indexes supported code files, Markdown, a bounded snapshot of open GitHub issues, and recent commit metadata. Semantic search and answer generation use the OpenAI API when `OPENAI_API_KEY` is set; otherwise it falls back to keyword search and verbatim source excerpts. Generated repository claims must cite retrieved evidence and include an exact source excerpt. Ask then fetches each cited file range from its indexed commit or each cited issue/commit from GitHub and confirms that the excerpt exists in the live record. Claims are labeled `source_checked`; this verifies provenance and the quoted source text, but does not prove that the model's interpretation is correct.

Issue matching requires source overlap and shows exact source lines. Its match score is a ranking aid, not a correctness guarantee. Issue snapshots refresh when the repository is indexed, on scheduled repository sync, or when `POST /issues/refresh` is called. The backend stores recent commit history and compares the indexed commit with GitHub during scheduled checks or manual refresh. Existing repositories without a saved per-file Git blob cache need one full index pass before later refreshes can reuse unchanged files.

## Approval-gated GitHub actions

The signed-in dashboard includes a floating Repo Fix Assistant. It accepts a public GitHub repository URL or an existing indexed snapshot plus a bug description, indexes an unfamiliar repository, and prepares the same bounded code-fix proposal for review. It displays the summary, changed files, diffs, and sandbox report, then links to Action approvals for the final human decision. The assistant does not bypass the approval flow or write directly to GitHub.

The dashboard can prepare an issue, a draft pull request from an existing branch, or a code-fix draft pull request from an indexed repository. Code-fix generation uses the indexed code and optionally a saved open issue, then stores complete replacement files, a unified diff, the target branch, and the indexed base commit in an immutable payload. Before saving the proposal, the backend fetches that exact public commit, overlays the patch in a temporary directory, and runs supported repository tests in Docker. The container has no network, no application credentials, a read-only source mount and root filesystem, 256 MiB writable temporary filesystems, and CPU, memory, process-count, output, and time limits. Only known language test commands are selected; repository code and tests run only inside this container. Dependencies are not downloaded or installed. If required packages are missing offline, Docker or a supported test suite is unavailable, that is shown in the review rather than treated as a pass. Test output and status are shown with the diff before approval. The generated change is limited to four retrieved source files. Approval creates a new `codex/fixes/...` branch, a single Git commit, and a draft pull request. If the target branch moved after indexing, execution stops and the fix must be regenerated against a fresh snapshot.

Preparing any proposal stores an immutable payload and its SHA-256 review hash locally. The approval checkbox sends an explicit confirmation and that same hash to `POST /actions/{proposal_id}/approve`. Only then does the API start the local FastMCP stdio server using the official MCP Python SDK and call its `execute_approved_github_action` tool. The server exposes only that hash-checked execution tool and atomically claims a proposal only when its saved status is `approved` and the payload hash still matches. Issue and pull-request writes are followed by a GET that confirms the saved record fields. Code-fix actions also read back the created commit and branch ref before opening the draft PR, then fetch the PR. If GitHub definitively rejects PR creation, the action checks for a PR created despite an uncertain response and deletes the temporary branch only when no PR exists. Draft pull requests are always sent with `draft: true`.

GitHub writes are disabled unless `GITHUB_WRITE_TOKEN` is configured in the backend environment. Use a dedicated token scoped to the intended repository with only the permissions needed: `Issues: write` to create issues, `Pull requests: write` to open PRs, and `Contents: write` to create the reviewed branch and commit for a code fix. Keep it on the backend, never in the browser or model prompt. Restart the backend after changing `.env`. The normal `GITHUB_TOKEN` remains for read requests. Preparing a proposal or opening the approvals page makes no GitHub write.

## Retrieval benchmark

`backend/benchmarks/retrieval_dataset.json` is a fixed 34-question set labeled for this application, including four deliberately unanswerable questions. Users can also import up to 200 labeled questions per repository; gold references must match indexed file paths, `issue:number`, or `commit:sha`. Choose a saved set in the Evaluation view to measure keyword, semantic, and hybrid retrieval, plus evidence sufficiency and refusal rates. Retrieval-only runs report Recall@K, Precision@K, Hit@K, and MRR. The optional answer-quality checkbox generates and live-checks answers for up to 40 questions per run using OpenAI and GitHub. It reports citation precision/recall against the benchmark's gold references, source-check rejection rate (generated claims rejected by citation/source matching), and a hallucination estimate on labeled unanswerable questions. These are reference- and unanswerable-set measures; they do not establish semantic correctness for every answer. Semantic ranking uses batched query embeddings when both stored repository embeddings and OpenAI query embeddings are available; otherwise it is reported unavailable and hybrid falls back to keyword retrieval. The benchmark endpoint is `POST /evaluation/retrieval`.

Demo sign-in is only for local evaluation and is not suitable for a public deployment.

For higher unauthenticated GitHub API limits, set `GITHUB_TOKEN` to a read-only token in the backend environment. Never place a GitHub write token in the model or browser.
