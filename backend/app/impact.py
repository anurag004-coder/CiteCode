"""Small static call-site scan for potential Python and JavaScript impact."""
import os
import re
from typing import Dict, List, Optional, Tuple

try:
    from tree_sitter_languages import get_parser
except ImportError:
    get_parser = None


LANGUAGE_BY_EXTENSION = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
}
DEFINITION_TYPES = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "generator_function_declaration", "method_definition", "class_declaration"},
}
CALL_TYPES = {"python": {"call"}, "javascript": {"call_expression"}}
IDENTIFIER_TYPES = {"identifier", "property_identifier", "private_property_identifier"}
NAME_PATTERN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def _row(node) -> int:
    point = node.start_point
    return (point[0] if isinstance(point, tuple) else point.row) + 1


def _named_child(node, field: str):
    try:
        return node.child_by_field_name(field)
    except Exception:
        return None


def _source_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _name_from_node(node, source: bytes) -> Optional[str]:
    name_node = _named_child(node, "name")
    if name_node is not None:
        value = _source_text(name_node, source).strip()
        return value or None
    return None


def _arrow_variable_name(node, source: bytes) -> Optional[str]:
    if node.type != "variable_declarator":
        return None
    value = _named_child(node, "value")
    if value is None or value.type not in {"arrow_function", "function_expression", "generator_function"}:
        return None
    name = _named_child(node, "name")
    return _source_text(name, source).strip() if name is not None else None


def _call_name(node, source: bytes) -> Optional[str]:
    function = _named_child(node, "function")
    if function is None:
        return None
    identifiers = [match.group(0) for match in NAME_PATTERN.finditer(_source_text(function, source))]
    return identifiers[-1] if identifiers else None


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    basename = normalized.rsplit("/", 1)[-1]
    return (
        basename.startswith("test_") or ".test." in basename or ".spec." in basename
        or any(part in {"test", "tests", "__tests__"} for part in normalized.split("/"))
    )


def _scan_file(path: str, content: str, language: str) -> Tuple[List[Dict], List[Dict]]:
    if get_parser is None:
        return [], []
    try:
        source = content.encode("utf-8")
        root = get_parser(language).parse(source).root_node
    except Exception:
        return [], []

    definitions: List[Dict] = []
    calls: List[Dict] = []

    def visit(node, enclosing: Optional[str] = None, enclosing_start: Optional[int] = None):
        name = None
        if node.type in DEFINITION_TYPES[language]:
            name = _name_from_node(node, source)
        if language == "javascript" and node.type == "variable_declarator":
            name = _arrow_variable_name(node, source) or name

        current_name = name or enclosing
        current_start = _row(node) if name else enclosing_start
        if name:
            definitions.append({"name": name, "path": path, "start_line": _row(node), "end_line": _row_end(node)})
        if node.type in CALL_TYPES[language]:
            called = _call_name(node, source)
            if called:
                calls.append({
                    "name": called,
                    "path": path,
                    "line": _row(node),
                    "caller": current_name or "<module>",
                    "caller_start_line": current_start,
                    "snippet": content.splitlines()[_row(node) - 1].strip()[:300]
                    if _row(node) <= len(content.splitlines()) else "",
                })
        for child in node.named_children:
            visit(child, current_name, current_start)

    visit(root)
    return definitions, calls


def _row_end(node) -> int:
    point = node.end_point
    return (point[0] if isinstance(point, tuple) else point.row) + 1


def analyze_repository(repository: Dict, files: Dict[str, Dict], path: Optional[str] = None,
                       symbol: Optional[str] = None, start_line: Optional[int] = None) -> Dict:
    scans = {}
    all_definitions: List[Dict] = []
    all_calls: List[Dict] = []
    for file_path, record in files.items():
        language = LANGUAGE_BY_EXTENSION.get(os.path.splitext(file_path)[1].lower())
        if language is None:
            continue
        definitions, calls = _scan_file(file_path, record.get("content", ""), language)
        scans[file_path] = (definitions, calls)
        all_definitions.extend(definitions)
        all_calls.extend(calls)

    if not path:
        targets = all_definitions
    else:
        targets = [item for item in scans.get(path, ([], []))[0]
                   if not symbol or (item["name"] == symbol and (start_line is None or item["start_line"] == start_line))]

    targets = sorted(targets, key=lambda item: (item["path"].lower(), item["start_line"], item["name"].lower()))
    if not path or not symbol:
        return {
            "repository": repository["full_name"], "commit_sha": repository["commit_sha"],
            "targets": targets[:3000], "potential_impact": None,
        }

    selected = next((item for item in targets if item["name"] == symbol and
                     (start_line is None or item["start_line"] == start_line)), None)
    if selected is None:
        return {"repository": repository["full_name"], "commit_sha": repository["commit_sha"], "targets": [], "potential_impact": None}

    same_name_definitions = [item for item in all_definitions if item["name"] == selected["name"]]
    candidates = []
    for call in all_calls:
        if call["name"] != selected["name"]:
            continue
        if call["path"] == selected["path"] and call["caller_start_line"] == selected["start_line"]:
            continue
        candidates.append(call)

    callers, tests = [], []
    for call in candidates:
        url = "https://github.com/{}/blob/{}/{}#L{}".format(
            repository["full_name"], repository["commit_sha"], call["path"], call["line"],
        )
        item = {**call, "url": url}
        (tests if _is_test_path(call["path"]) else callers).append(item)

    return {
        "repository": repository["full_name"],
        "commit_sha": repository["commit_sha"],
        "targets": targets[:3000],
        "potential_impact": {
            "target": selected,
            "matching_definition_count": len(same_name_definitions),
            "other_matching_definitions": [item for item in same_name_definitions
                                           if item["path"] != selected["path"] or item["start_line"] != selected["start_line"]],
            "direct_callers": callers[:500],
            "likely_tests": tests[:500],
            "limitations": "Potential impact from static call-site matching. Dynamic calls may be missed; matching names can resolve ambiguously.",
        },
    }
