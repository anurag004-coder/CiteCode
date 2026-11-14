"""Run detected repository checks against a patch in a constrained Docker container."""
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 160 * 1024 * 1024
MAX_ARCHIVE_FILES = 5000
MAX_OUTPUT_CHARS = 6000
MAX_COMMAND_SECONDS = 75
MAX_VALIDATION_SECONDS = 120
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "vendor", "target", "dist", "build", "__pycache__"}


def _result(status: str, message: str, commands: Optional[List[Dict]] = None) -> Dict:
    return {
        "status": status,
        "message": message,
        "commands": commands or [],
        "network_disabled": True,
        "sandbox": "Docker" if status != "unavailable" else None,
    }


def _setup_is_missing(output: str) -> bool:
    text = output.lower()
    markers = (
        "no module named ", "cannot find module", "module not found", "no matching distribution",
        "could not resolve dependencies", "could not resolve all files", "module lookup disabled",
        "failed to download", "no cached version", "unable to resolve dependency",
    )
    return any(marker in text for marker in markers)


def _download_archive(owner: str, name: str, commit_sha: str) -> bytes:
    url = "https://api.github.com/repos/{}/{}/tarball/{}".format(
        quote(owner, safe=""), quote(name, safe=""), quote(commit_sha, safe="")
    )
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Codebase-Whisperer-Sandbox/1.0",
    })
    try:
        with urlopen(request, timeout=30) as response:
            final_host = urlsplit(response.geturl()).hostname
            if final_host not in {"api.github.com", "codeload.github.com"}:
                raise ValueError("GitHub returned an unexpected archive host.")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ARCHIVE_BYTES:
                raise ValueError("The repository archive is too large for isolated validation.")
            data = response.read(MAX_ARCHIVE_BYTES + 1)
    except HTTPError as error:
        raise ValueError("GitHub could not provide the pinned repository archive (HTTP {}).".format(error.code))
    except (URLError, TimeoutError) as error:
        raise ValueError("Could not download the pinned repository archive: {}".format(str(error)[:200]))
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("The repository archive is too large for isolated validation.")
    return data


def _safe_extract(archive_bytes: bytes, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o777)
    try:
        archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")
    except (tarfile.TarError, OSError) as error:
        raise ValueError("GitHub returned an invalid source archive: {}".format(str(error)[:200]))

    with archive:
        members = archive.getmembers()
        if len(members) > MAX_ARCHIVE_FILES:
            raise ValueError("The repository archive contains too many entries for validation.")
        roots = {PurePosixPath(member.name).parts[0] for member in members if PurePosixPath(member.name).parts}
        if len(roots) != 1:
            raise ValueError("The repository archive did not have a single safe root directory.")
        archive_root = next(iter(roots))
        if archive_root in {".", ".."} or "/" in archive_root or "\\" in archive_root:
            raise ValueError("The repository archive has an unsafe root directory.")
        extracted_bytes = 0
        extracted_files = 0

        for member in members:
            raw_parts = PurePosixPath(member.name).parts
            if not raw_parts or raw_parts[0] != archive_root or "\\" in member.name:
                continue
            relative_parts = raw_parts[1:]
            if not relative_parts:
                continue
            if any(part in {"", ".", ".."} for part in relative_parts):
                continue
            target = destination.joinpath(*relative_parts)
            try:
                target.resolve().relative_to(destination.resolve())
            except ValueError:
                continue

            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o777)
                continue
            if not member.isfile():
                # Never materialize symlinks, hardlinks, devices, or other special entries.
                continue
            if member.size < 0 or member.size > MAX_EXTRACTED_BYTES:
                raise ValueError("The repository archive has a file that is too large to validate.")
            extracted_bytes += member.size
            extracted_files += 1
            if extracted_bytes > MAX_EXTRACTED_BYTES or extracted_files > MAX_ARCHIVE_FILES:
                raise ValueError("The expanded repository archive is too large for validation.")

            target.parent.mkdir(parents=True, exist_ok=True)
            for directory in [target.parent, *target.parent.parents]:
                if directory == destination.parent:
                    break
                try:
                    directory.chmod(0o777)
                except OSError:
                    pass
            source = archive.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as output:
                remaining = member.size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("The repository archive ended before a file was complete.")
                    output.write(block)
                    remaining -= len(block)
            target.chmod(0o666)

    if extracted_files == 0:
        raise ValueError("The repository archive contained no regular source files.")
    return destination


def _overlay_changes(root: Path, changes: List[Dict]) -> None:
    for change in changes:
        path = str(change.get("path") or "")
        parts = PurePosixPath(path).parts
        if not path or path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("The reviewed patch contains an unsafe file path.")
        target = root.joinpath(*parts)
        try:
            target.resolve().relative_to(root.resolve())
        except ValueError:
            raise ValueError("The reviewed patch points outside the temporary repository.")
        if target.is_symlink() or not target.is_file():
            raise ValueError("{} is not a regular source file in the pinned archive.".format(path))
        content = change.get("content")
        if not isinstance(content, str):
            raise ValueError("The reviewed patch has invalid file content.")
        target.write_text(content, encoding="utf-8")
        target.chmod(0o666)


def _walk_files(root: Path):
    for current, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name not in SKIP_DIRS and not name.startswith(".")]
        for name in files:
            yield Path(current) / name


def _has_pytest(root: Path, test_files: List[Path]) -> bool:
    for manifest in (root / "pytest.ini", root / "pyproject.toml", root / "tox.ini", root / "setup.cfg"):
        try:
            if manifest.is_file() and "pytest" in manifest.read_text(encoding="utf-8", errors="replace").lower():
                return True
        except OSError:
            continue
    for test_file in test_files[:20]:
        try:
            source = test_file.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        if "import pytest" in source or "from pytest" in source:
            return True
    return False


def _detect_commands(root: Path, changed_paths: List[str]) -> List[Dict]:
    files = list(_walk_files(root))
    relative = {path.relative_to(root).as_posix() for path in files}
    commands = []

    package_file = root / "package.json"
    if package_file.is_file():
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            package = {}
        if not isinstance(package, dict):
            package = {}
        if (package.get("scripts") or {}).get("test"):
            commands.append({
                "label": "npm test (offline)",
                "image": "node:22.13.1-bookworm-slim",
                "argv": ["npm", "--offline", "--ignore-scripts", "run", "test"],
                "kind": "test",
                "extensions": {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"},
            })
        elif any(name.endswith((".test.js", ".spec.js", ".test.mjs", ".spec.mjs")) for name in relative):
            commands.append({
                "label": "Node built-in tests",
                "image": "node:22.13.1-bookworm-slim",
                "argv": ["node", "--test"],
                "kind": "test",
                "extensions": {".js", ".mjs", ".cjs"},
            })

    python_tests = [
        path for path in files
        if path.suffix.lower() == ".py"
        and (path.name.startswith("test_") or path.name.endswith("_test.py") or path.parent.name in {"tests", "test"})
    ]
    if python_tests:
        pytest = _has_pytest(root, python_tests)
        commands.append({
            "label": "pytest (offline)" if pytest else "Python unittest discovery",
            "image": "python:3.12.8-slim-bookworm",
            "argv": ["python", "-m", "pytest", "-q"] if pytest else ["python", "-m", "unittest", "discover", "-v"],
            "kind": "test",
            "extensions": {".py"},
        })

    if "go.mod" in relative and any(path.endswith("_test.go") for path in relative):
        go_mode = "vendor" if (root / "vendor" / "modules.txt").is_file() else "readonly"
        commands.append({
            "label": "go test (offline)",
            "image": "golang:1.23.5-bookworm",
            "argv": ["go", "test", "-mod=" + go_mode, "./..."],
            "kind": "test",
            "extensions": {".go"},
        })

    if "Cargo.toml" in relative:
        commands.append({
            "label": "cargo test (offline)",
            "image": "rust:1.84.0-slim-bookworm",
            "argv": ["cargo", "test", "--offline"],
            "kind": "test",
            "extensions": {".rs"},
        })

    if "pom.xml" in relative and any(path.startswith("src/test/") for path in relative):
        commands.append({
            "label": "Maven test (offline)",
            "image": "maven:3.9.9-eclipse-temurin-21",
            "argv": ["mvn", "--offline", "-B", "test"],
            "kind": "test",
            "extensions": {".java"},
        })

    changed_extensions = {
        Path(path).suffix.lower() for path in changed_paths
    }
    commands.sort(
        key=lambda item: (0 if item["extensions"].intersection(changed_extensions) else 1, item["label"])
    )
    return commands[:3]


def _capture_container(command: Dict, root: Path) -> Dict:
    docker = shutil.which("docker")
    if not docker:
        return {"label": command["label"], "status": "unavailable", "exit_code": None, "output": "Docker is not installed."}
    container_name = "cw-check-{}".format(uuid.uuid4().hex[:16])
    args = [
        docker, "run", "--rm", "--name", container_name, "--pull=missing",
        "--network=none", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
        "--tmpfs", "/workspace:rw,nosuid,nodev,size=256m",
        "--pids-limit=64", "--memory=1g", "--memory-swap=1g", "--cpus=1",
        "--security-opt=no-new-privileges", "--cap-drop=ALL", "--user=65534:65534",
        "--workdir=/workspace", "--mount", "type=bind,source={},target=/source,readonly".format(str(root)),
        "--env", "HOME=/tmp", "--env", "CI=true", "--entrypoint", "/bin/sh",
        command["image"], "-c", "cp -a /source/. /workspace/ && exec \"$@\"", "sandbox-runner",
        *command["argv"],
    ]
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as error:
        return {"label": command["label"], "status": "unavailable", "exit_code": None, "output": str(error)[:500]}

    output = []
    output_size = [0]

    def drain_output():
        if process.stdout is None:
            return
        while True:
            block = process.stdout.read(4096)
            if not block:
                break
            if output_size[0] < MAX_OUTPUT_CHARS:
                remaining = MAX_OUTPUT_CHARS - output_size[0]
                piece = block[:remaining]
                output.append(piece.decode("utf-8", "replace"))
                output_size[0] += len(piece)

    reader = threading.Thread(target=drain_output, daemon=True)
    reader.start()
    try:
        exit_code = process.wait(timeout=MAX_COMMAND_SECONDS)
        reader.join(timeout=2)
        text = "".join(output)
        if output_size[0] >= MAX_OUTPUT_CHARS:
            text += "\n[Output truncated.]"
        status = "passed" if exit_code == 0 else ("setup_required" if _setup_is_missing(text) else "failed")
        return {"label": command["label"], "status": status, "exit_code": exit_code, "output": text}
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        reader.join(timeout=2)
        try:
            subprocess.run([docker, "rm", "-f", container_name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
        text = "".join(output) + "\n[Validation stopped after {} seconds.]".format(MAX_COMMAND_SECONDS)
        return {"label": command["label"], "status": "timed_out", "exit_code": None, "output": text}


def _docker_available() -> Optional[str]:
    docker = shutil.which("docker")
    if not docker:
        return "Docker is not installed on the backend host."
    try:
        result = subprocess.run(
            [docker, "info", "--format", "{{.ServerVersion}}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return "Docker is unavailable: {}".format(str(error)[:200])
    if result.returncode != 0:
        return "Docker daemon is not available. Start Docker, then prepare the code fix again."
    return None


def validate_patch_in_sandbox(owner: str, name: str, commit_sha: str, changes: List[Dict]) -> Dict:
    """Fetch the pinned public snapshot, overlay the patch, and run detected checks offline."""
    unavailable = _docker_available()
    if unavailable:
        return _result("unavailable", unavailable)
    try:
        archive_bytes = _download_archive(owner, name, commit_sha)
        with tempfile.TemporaryDirectory(prefix="codebase-whisperer-discovery-") as discovery_temp:
            Path(discovery_temp).chmod(0o755)
            discovery_root = _safe_extract(archive_bytes, Path(discovery_temp) / "repo")
            _overlay_changes(discovery_root, changes)
            commands = _detect_commands(discovery_root, [item.get("path", "") for item in changes])
        if not commands:
            return _result(
                "no_tests",
                "No supported test suite was detected in the repository. The patch is available for review, but no tests were run.",
            )

        results = []
        started_at = time.monotonic()
        for command in commands:
            if time.monotonic() - started_at >= MAX_VALIDATION_SECONDS:
                results.append({
                    "label": command["label"], "status": "timed_out", "exit_code": None,
                    "output": "Validation time budget reached before this check could start.",
                })
                break
            with tempfile.TemporaryDirectory(prefix="codebase-whisperer-check-") as command_temp:
                Path(command_temp).chmod(0o755)
                root = _safe_extract(archive_bytes, Path(command_temp) / "repo")
                _overlay_changes(root, changes)
                check = _capture_container(command, root)
                results.append(check)
            if check["status"] == "unavailable":
                break

        if any(item["status"] in {"failed", "timed_out"} for item in results):
            status = "failed" if all(item["status"] != "timed_out" for item in results) else "timed_out"
            message = "One or more isolated checks did not pass. Review the output before approving."
        elif results and all(item["status"] == "passed" for item in results):
            status = "passed"
            message = "All detected isolated checks passed."
        elif results and any(item["status"] == "setup_required" for item in results):
            status = "setup_required"
            message = "A check could not run because a dependency was not available offline. Review the output before approving."
        else:
            status = "unavailable"
            message = "The detected checks could not run in the isolated environment."
        return _result(status, message, results)
    except Exception as error:
        return _result("unavailable", "Isolated validation could not be completed: {}".format(str(error)[:400]))
