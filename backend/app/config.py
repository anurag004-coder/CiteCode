import os
from pathlib import Path
from typing import List


BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

DATA_DIR = Path(os.getenv("CODEBASE_DATA_DIR", str(BACKEND_DIR / "data"))).expanduser()
DATABASE_PATH = DATA_DIR / "codebase_whisperer.sqlite3"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_WRITE_TOKEN = os.getenv("GITHUB_WRITE_TOKEN", "").strip()

MAX_REPO_FILES = int(os.getenv("MAX_REPO_FILES", "1200"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", "150000"))
MAX_REPO_BYTES = int(os.getenv("MAX_REPO_BYTES", "20000000"))
MAX_CHUNK_LINES = int(os.getenv("MAX_CHUNK_LINES", "120"))
MAX_CHUNKS_PER_REPO = int(os.getenv("MAX_CHUNKS_PER_REPO", "8000"))
MIN_LEXICAL_COVERAGE = float(os.getenv("MIN_LEXICAL_COVERAGE", "0.2"))
MIN_COSINE_SIMILARITY = float(os.getenv("MIN_COSINE_SIMILARITY", "0.25"))
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "14"))
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
REPOSITORY_SYNC_INTERVAL_MINUTES = int(os.getenv("REPOSITORY_SYNC_INTERVAL_MINUTES", "60"))

FRONTEND_ORIGINS: List[str] = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]
