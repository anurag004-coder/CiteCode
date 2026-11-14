import hashlib
import re
from typing import List, Optional, Tuple

from .config import MAX_CHUNK_LINES
from .models import Chunk


LANGUAGE_BY_EXTENSION = {
    ".py": "python", ".pyw": "python", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".java": "java", ".go": "go", ".rs": "rust", ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".cs": "c_sharp", ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala", ".sh": "bash",
    ".bash": "bash", ".sql": "sql", ".vue": "vue", ".svelte": "svelte",
}
CLASS_TYPES = {
    "class_definition", "class_declaration", "class_specifier", "struct_specifier",
    "struct_item", "interface_declaration", "trait_item", "enum_declaration",
    "enum_item", "type_declaration", "record_declaration",
}
DEFINITION_TYPES = CLASS_TYPES | {
    "function_definition", "function_declaration", "generator_function_declaration",
    "method_definition", "method_declaration", "constructor_declaration",
    "function_item", "method_declaration", "method_definition",
    "function_declarator", "function_definition", "arrow_function",
}
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")

try:
    from tree_sitter_languages import get_parser
except ImportError:
    get_parser = None


def _chunk_id(repo_id: str, path: str, start_line: int, text: str) -> Tuple[str, str]:
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    identity = "\0".join((repo_id, path, str(start_line), content_hash))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32], content_hash


def _make_chunk(
    repo_id: str,
    path: str,
    commit_sha: str,
    source_type: str,
    symbol: Optional[str],
    start_line: int,
    text: str,
) -> Optional[Chunk]:
    normalized = text.strip("\n")
    if not normalized.strip():
        return None
    chunk_id, content_hash = _chunk_id(repo_id, path, start_line, normalized)
    end_line = start_line + max(0, len(normalized.splitlines()) - 1)
    return Chunk(
        id=chunk_id,
        repo_id=repo_id,
        source_type=source_type,
        path=path,
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        commit_sha=commit_sha,
        text=normalized,
        content_hash=content_hash,
    )


def _split_lines(
    repo_id: str,
    path: str,
    commit_sha: str,
    source_type: str,
    symbol: Optional[str],
    start_line: int,
    text: str,
) -> List[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    result = []
    for offset in range(0, len(lines), MAX_CHUNK_LINES):
        piece = "\n".join(lines[offset : offset + MAX_CHUNK_LINES])
        piece_symbol = symbol
        if len(lines) > MAX_CHUNK_LINES and symbol:
            piece_symbol = "{} (part {})".format(symbol, offset // MAX_CHUNK_LINES + 1)
        chunk = _make_chunk(
            repo_id, path, commit_sha, source_type, piece_symbol, start_line + offset, piece
        )
        if chunk:
            result.append(chunk)
    return result


def _markdown_chunks(repo_id: str, path: str, commit_sha: str, text: str) -> List[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    headings = [i for i, line in enumerate(lines) if re.match(r"^\s{0,3}#{1,6}\s+", line)]
    boundaries = [0] + [index for index in headings if index > 0] + [len(lines)]
    result = []
    for section_index in range(len(boundaries) - 1):
        start, end = boundaries[section_index], boundaries[section_index + 1]
        section = "\n".join(lines[start:end])
        first_heading = next(
            (line.lstrip("# ").strip() for line in lines[start:end] if re.match(r"^\s{0,3}#{1,6}\s+", line)),
            "Introduction" if start == 0 else "Documentation",
        )
        result.extend(
            _split_lines(repo_id, path, commit_sha, "documentation", first_heading, start + 1, section)
        )
    return result


def _node_name(node, source: bytes) -> Optional[str]:
    try:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return source[name_node.start_byte : name_node.end_byte].decode("utf-8", "replace")
    except Exception:
        pass
    return None


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _tree_sitter_chunks(repo_id: str, path: str, commit_sha: str, text: str) -> List[Chunk]:
    if get_parser is None:
        return []
    import os

    language = LANGUAGE_BY_EXTENSION.get(os.path.splitext(path)[1].lower())
    if not language:
        return []
    try:
        parser = get_parser(language)
        source = text.encode("utf-8")
        tree = parser.parse(source)
        root = tree.root_node
    except Exception:
        return []

    nodes = []

    def visit(node):
        if node.type in DEFINITION_TYPES:
            start_row = node.start_point[0] if isinstance(node.start_point, tuple) else node.start_point.row
            body = _node_text(node, source)
            symbol = _node_name(node, source)
            nodes.append((start_row + 1, symbol or node.type, body))
            return
        for child in node.named_children:
            visit(child)

    visit(root)
    if not nodes:
        return []

    result = []
    for start_line, symbol, body in nodes:
        result.extend(
            _split_lines(repo_id, path, commit_sha, "code", symbol, start_line, body)
        )
    return result


def chunk_file(repo_id: str, path: str, commit_sha: str, text: str) -> List[Chunk]:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if suffix in {"md", "markdown"}:
        return _markdown_chunks(repo_id, path, commit_sha, text)

    chunks = _tree_sitter_chunks(repo_id, path, commit_sha, text)
    if chunks:
        return chunks
    return _split_lines(repo_id, path, commit_sha, "code", None, 1, text)
