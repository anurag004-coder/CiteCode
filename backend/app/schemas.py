import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("Enter a valid email address.")
        return value


class LoginRequest(EmailRequest):
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: str
    onboarding_completed: bool = False
    experience_level: Optional[str] = None
    onboarding_goal: Optional[str] = None
    languages_known: List[str] = Field(default_factory=list)
    setup_os: str = "linux"
    uses_docker: bool = True
    time_available: str = "1_day"
    explanation_language: str = "English"


class OnboardingSetupRequest(BaseModel):
    experience_level: Optional[Literal["beginner", "intermediate", "advanced"]] = None
    goal: Optional[Literal["understand_code", "fix_bug", "add_feature", "review_prs", "just_learn"]] = None
    languages_known: List[Literal[
        "JavaScript", "TypeScript", "Python", "Java", "C", "C++", "C#", "Go", "Rust",
        "PHP", "Ruby", "Swift", "Kotlin", "SQL", "None of these",
    ]] = Field(default_factory=list, max_length=15)
    setup_os: Literal["windows", "macos", "linux"] = "linux"
    uses_docker: bool = True
    time_available: Literal["1_hour", "1_day", "1_week"] = "1_day"
    explanation_language: Literal[
        "English", "Hindi", "Bengali", "Spanish", "French", "German", "Portuguese",
        "Japanese", "Chinese",
    ] = "English"

    @model_validator(mode="after")
    def validate_known_languages(self):
        if "None of these" in self.languages_known and len(self.languages_known) > 1:
            raise ValueError("Choose 'None of these' by itself, or select the languages you know.")
        self.languages_known = list(dict.fromkeys(self.languages_known))
        return self


class GuideRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)
    experience_level: Optional[Literal["beginner", "intermediate", "advanced"]] = None
    goal: Optional[str] = Field(default=None, max_length=300)


class IndexRequest(BaseModel):
    repository_url: str = Field(min_length=12, max_length=500)


class IndexResponse(BaseModel):
    repo_id: str
    full_name: str
    commit_sha: str
    default_branch: str
    file_count: int
    chunk_count: int
    issue_count: int = 0
    commit_count: int = 0
    skipped_files: int
    vector_search: bool
    warning: Optional[str] = None


class Citation(BaseModel):
    path: str
    symbol: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    commit_sha: str
    source_type: str
    url: str
    reference_key: Optional[str] = None


class Claim(BaseModel):
    text: str
    status: Literal["source_checked", "assumption"]
    verification_note: str
    citations: List[Citation] = Field(default_factory=list)


class GuideSection(BaseModel):
    title: str
    text: str
    status: Literal["source_checked", "assumption"]
    verification_note: str
    citations: List[Citation] = Field(default_factory=list)


class GuideResponse(BaseModel):
    repo_id: str
    repository: str
    commit_sha: str
    mode: Literal["generated", "extractive"]
    title: str
    summary: str
    sections: List[GuideSection] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    searched_paths: List[str] = Field(default_factory=list)


class IssueRefreshRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)


class IssueRefreshResponse(BaseModel):
    repo_id: str
    issue_count: int
    synced_at: str


class IssueRecommendation(BaseModel):
    number: int
    title: str
    summary: str
    url: str
    labels: List[str] = Field(default_factory=list)
    updated_at: str
    assignee_count: int
    match_score: int
    fit_reasons: List[str] = Field(default_factory=list)
    related_files: List[Citation] = Field(default_factory=list)


class IssueMatchesResponse(BaseModel):
    repo_id: str
    repository: str
    commit_sha: str
    issue_count: int
    synced_at: Optional[str] = None
    recommendations: List[IssueRecommendation] = Field(default_factory=list)
    note: Optional[str] = None


class ChangeRefreshRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)


class CommitRecord(BaseModel):
    sha: str
    message: str
    author: str
    committed_at: str
    html_url: str


class ChangedFile(BaseModel):
    path: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str = ""
    html_url: str = ""


class ChangeSummaryResponse(BaseModel):
    repo_id: str
    repository: str
    current_snapshot_sha: str
    base_commit_sha: Optional[str] = None
    compared_head_sha: Optional[str] = None
    synced_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    mode: Literal["generated", "computed", "none"] = "none"
    summary: str
    verification_note: str
    comparison_url: Optional[str] = None
    commit_total: int = 0
    file_total: int = 0
    commits: List[CommitRecord] = Field(default_factory=list)
    recent_commits: List[CommitRecord] = Field(default_factory=list)
    files: List[ChangedFile] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=12)
    explanation_language: Optional[Literal[
        "English", "Hindi", "Bengali", "Spanish", "French", "German", "Portuguese",
        "Japanese", "Chinese",
    ]] = None


class AskResponse(BaseModel):
    repo_id: str
    repository: str
    commit_sha: str
    mode: Literal["generated", "extractive", "refusal"]
    answer: str
    claims: List[Claim] = Field(default_factory=list)
    refusal_reason: Optional[str] = None
    searched_paths: List[str] = Field(default_factory=list)


class RepositorySummary(BaseModel):
    id: str
    full_name: str
    url: str
    default_branch: str
    commit_sha: str
    indexed_at: str
    file_count: int
    chunk_count: int
    issue_count: int = 0
    commit_count: int = 0
    sync_status: Literal["current", "stale", "syncing", "failed"] = "current"
    latest_sha: Optional[str] = None
    sync_checked_at: Optional[str] = None
    last_sync_at: Optional[str] = None
    sync_error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    openai_configured: bool


class GitHubActionProposalRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)
    action_type: Literal["issue", "draft_pr"]
    title: str = Field(min_length=3, max_length=256)
    body: str = Field(min_length=1, max_length=12000)
    labels: List[str] = Field(default_factory=list, max_length=10)
    head: Optional[str] = Field(default=None, max_length=255)
    base: Optional[str] = Field(default=None, max_length=255)

    @field_validator("title", "body", "head", "base")
    @classmethod
    def trim_action_text(cls, value):
        return value.strip() if value is not None else value

    @field_validator("labels")
    @classmethod
    def clean_labels(cls, values):
        return list(dict.fromkeys(value.strip()[:50] for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_action_target(self):
        if not self.title or not self.body:
            raise ValueError("Add a non-empty title and description.")
        if self.action_type == "draft_pr" and (not self.head or not self.base):
            raise ValueError("A draft pull request needs both source and target branches.")
        if self.action_type == "issue" and (self.head or self.base):
            raise ValueError("Branch fields are only used for draft pull requests.")
        if self.action_type == "draft_pr" and self.head == self.base:
            raise ValueError("Choose different source and target branches.")
        return self


class CodeFixProposalRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)
    title: str = Field(min_length=3, max_length=256)
    task: str = Field(min_length=3, max_length=5000)
    issue_number: Optional[int] = Field(default=None, ge=1)

    @field_validator("title", "task")
    @classmethod
    def trim_code_fix_text(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def require_code_fix_details(self):
        if not self.title or not self.task:
            raise ValueError("Enter a short title and describe the bug or requested change.")
        return self


class GitHubActionApprovalRequest(BaseModel):
    confirm: bool
    payload_hash: str = Field(min_length=64, max_length=64)


class RetrievalBenchmarkRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)
    top_k: int = Field(default=5, ge=1, le=20)
    benchmark_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    include_answer_quality: bool = False


class BenchmarkCaseInput(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    expected_refs: List[str] = Field(default_factory=list, max_length=20)
    answerable: bool

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question cannot be empty.")
        return value

    @field_validator("expected_refs")
    @classmethod
    def clean_expected_refs(cls, values: List[str]) -> List[str]:
        return list(dict.fromkeys(value.strip()[:1000] for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_labels(self):
        if self.answerable and not self.expected_refs:
            raise ValueError("Answerable questions need at least one expected file, issue, or commit reference.")
        if not self.answerable and self.expected_refs:
            raise ValueError("Unanswerable questions must have an empty expected_refs list.")
        return self


class BenchmarkDatasetCreateRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=300)
    name: str = Field(min_length=2, max_length=120)
    cases: List[BenchmarkCaseInput] = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Benchmark name cannot be empty.")
        return value
