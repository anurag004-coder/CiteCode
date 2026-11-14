from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Chunk:
    id: str
    repo_id: str
    source_type: str
    path: str
    symbol: Optional[str]
    start_line: int
    end_line: int
    commit_sha: str
    text: str
    content_hash: str
    embedding: Optional[List[float]] = None

    def to_record(self):
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "source_type": self.source_type,
            "path": self.path,
            "symbol": self.symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "commit_sha": self.commit_sha,
            "text": self.text,
            "content_hash": self.content_hash,
            "embedding": self.embedding,
        }
