from datetime import datetime, timezone
from typing import Dict, List

from .llm import generate_change_summary


def _computed_summary(comparison: Dict) -> str:
    files = comparison.get("files", [])
    additions = sum(int(item.get("additions", 0)) for item in files)
    deletions = sum(int(item.get("deletions", 0)) for item in files)
    shown = len(files)
    total = int(comparison.get("total_files", shown))
    commits = comparison.get("commits", [])
    messages = []
    for item in commits[:3]:
        message = str(item.get("message", "")).splitlines()[0].strip()
        if message:
            messages.append(message[:160])
    subject = "Recent commit messages: {}.".format("; ".join(messages)) if messages else "No commit messages were returned."
    file_scope = "{} changed files".format(total)
    if shown < total:
        file_scope += " ({} file details shown)".format(shown)
    return "GitHub reports {} commit(s) affecting {}. The returned file details contain +{} and -{} lines. {}".format(
        int(comparison.get("total_commits", len(commits))),
        file_scope,
        additions,
        deletions,
        subject,
    )


def build_change_snapshot(
    base_sha: str,
    head_sha: str,
    comparison: Dict,
    explanation_language: str = "English",
) -> Dict:
    commits: List[Dict] = comparison.get("commits", [])
    files: List[Dict] = comparison.get("files", [])
    generated = generate_change_summary(explanation_language, commits, files)
    generated_summary = str(generated.get("summary", "")).strip() if generated else ""
    gaps = []
    raw_gaps = generated.get("gaps", []) if generated else []
    if isinstance(raw_gaps, list):
        gaps.extend(str(item).strip()[:300] for item in raw_gaps if str(item).strip())
    missing_patches = sum(1 for item in files if not item.get("patch"))
    if missing_patches:
        gaps.append("GitHub did not return diff text for {} of the displayed files.".format(missing_patches))
    if int(comparison.get("total_files", len(files))) > len(files):
        gaps.append("GitHub returned only the first {} file details for this comparison.".format(len(files)))

    if generated_summary:
        summary = generated_summary[:1500]
        mode = "generated"
        verification_note = "AI interpretation based on the linked GitHub commits and available diff excerpts. Verify details in the source links."
    else:
        summary = _computed_summary(comparison)
        mode = "computed"
        verification_note = "Counts and commit messages come directly from GitHub. This summary does not interpret code behavior."
        gaps.append("AI change explanation was unavailable; showing commit metadata and diff counts instead.")

    now = datetime.now(timezone.utc).isoformat()
    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "synced_at": now,
        "checked_at": now,
        "summary": summary,
        "mode": mode,
        "verification_note": verification_note,
        "comparison_url": comparison.get("compare_url", ""),
        "commit_total": int(comparison.get("total_commits", len(commits))),
        "file_total": int(comparison.get("total_files", len(files))),
        "commits": commits,
        "files": files,
        "gaps": gaps[:8],
    }
