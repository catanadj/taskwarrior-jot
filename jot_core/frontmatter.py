from __future__ import annotations

import fcntl
import errno
import json
import os
import shutil
import tempfile
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


FrontMatter = OrderedDict[str, Any]

DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
DEFAULT_STALE_LOCK_SECONDS = 300.0
LOCK_POLL_SECONDS = 0.05


def read_document(path: Path) -> tuple[FrontMatter, str]:
    text = path.read_text(encoding="utf-8")
    return parse_document(text)


def write_document(path: Path, metadata: FrontMatter, body: str) -> None:
    atomic_write_text(path, render_document(metadata, body))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, existing_mode)
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        if not _acquire_flock(lock_handle, lock_path):
            with _exclusive_lock_dir(lock_path):
                yield
            return
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_lock_dir(lock_path: Path) -> Iterator[None]:
    lock_dir = lock_path.with_suffix(lock_path.suffix + ".d")
    timeout = _lock_duration("JOT_LOCK_TIMEOUT", DEFAULT_LOCK_TIMEOUT_SECONDS)
    stale_after = _lock_duration("JOT_LOCK_STALE_AFTER", DEFAULT_STALE_LOCK_SECONDS)
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock_dir.mkdir()
            _write_lock_owner(lock_dir)
            break
        except FileExistsError:
            if _lock_dir_is_stale(lock_dir, stale_after=stale_after):
                _remove_stale_lock_dir(lock_dir)
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError(f"timed out waiting for file lock: {lock_path}")
            time.sleep(LOCK_POLL_SECONDS)
        except Exception:
            if lock_dir.exists():
                shutil.rmtree(lock_dir, ignore_errors=True)
            raise
    try:
        yield
    finally:
        try:
            (lock_dir / "owner.json").unlink(missing_ok=True)
            lock_dir.rmdir()
        except FileNotFoundError:
            pass


def find_stale_lock_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    stale_after = _lock_duration("JOT_LOCK_STALE_AFTER", DEFAULT_STALE_LOCK_SECONDS)
    return [
        path
        for path in sorted(root.rglob(".*.lock.d"))
        if path.is_dir() and _lock_dir_is_stale(path, stale_after=stale_after)
    ]


def repair_stale_lock_dirs(root: Path) -> list[Path]:
    repaired: list[Path] = []
    for path in find_stale_lock_dirs(root):
        if _remove_stale_lock_dir(path):
            repaired.append(path)
    return repaired


def _acquire_flock(lock_handle, lock_path: Path) -> bool:
    timeout = _lock_duration("JOT_LOCK_TIMEOUT", DEFAULT_LOCK_TIMEOUT_SECONDS)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno == errno.ENOSYS:
                return False
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError(f"timed out waiting for file lock: {lock_path}") from exc
            time.sleep(LOCK_POLL_SECONDS)


def _write_lock_owner(lock_dir: Path) -> None:
    payload = {
        "pid": os.getpid(),
        "created": time.time(),
    }
    owner_path = lock_dir / "owner.json"
    with owner_path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())


def _lock_dir_is_stale(lock_dir: Path, *, stale_after: float) -> bool:
    try:
        fallback_created = lock_dir.stat().st_mtime
    except FileNotFoundError:
        return False
    owner_path = lock_dir / "owner.json"
    try:
        payload = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return time.time() - fallback_created >= stale_after

    try:
        pid = int(payload.get("pid") or 0)
        created = float(payload.get("created") or fallback_created)
    except (TypeError, ValueError, AttributeError):
        return time.time() - fallback_created >= stale_after
    if pid > 0 and not _process_exists(pid):
        return True
    if pid > 0:
        return False
    return time.time() - created >= stale_after


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_stale_lock_dir(lock_dir: Path) -> bool:
    quarantine = lock_dir.with_name(f"{lock_dir.name}.stale-{os.getpid()}-{time.time_ns()}")
    try:
        os.replace(lock_dir, quarantine)
    except FileNotFoundError:
        return False
    shutil.rmtree(quarantine, ignore_errors=True)
    return True


def _lock_duration(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@contextmanager
def locked_document(path: Path) -> Iterator[tuple[FrontMatter, str]]:
    """Lock a note across a complete read-modify-write transaction."""
    with exclusive_file_lock(path):
        yield read_document(path)


def parse_document(text: str) -> tuple[FrontMatter, str]:
    raw_text = str(text or "")
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return OrderedDict(), raw_text

    metadata: FrontMatter = OrderedDict()
    idx = 1
    current_key: str | None = None
    current_list: list[str] = []
    closed = False

    while idx < len(lines):
        line = lines[idx]
        idx += 1
        if line.strip() == "---":
            closed = True
            break
        if current_key and line.startswith("  - "):
            current_list.append(line[4:].strip())
            continue
        if current_key is not None:
            metadata[current_key] = list(current_list)
            current_key = None
            current_list = []
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value:
            metadata[key] = _parse_scalar(value)
        else:
            current_key = key
            current_list = []

    if not closed:
        raise RuntimeError("unterminated front matter: missing closing '---'")

    if current_key is not None:
        metadata[current_key] = list(current_list)

    body_lines = lines[idx:]
    body = "\n".join(body_lines)
    if raw_text.endswith("\n"):
        body += "\n"
    return metadata, body


def render_document(metadata: FrontMatter, body: str) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {_render_scalar(value)}")
    lines.append("---")
    lines.append("")
    normalized_body = str(body or "")
    if normalized_body.startswith("\n"):
        normalized_body = normalized_body[1:]
    lines.append(normalized_body.rstrip("\n"))
    return "\n".join(lines).rstrip("\n") + "\n"


def update_metadata(path: Path, updates: dict[str, Any]) -> None:
    metadata, body = read_document(path)
    for key, value in updates.items():
        metadata[key] = value
    write_document(path, metadata, body)


def _parse_scalar(value: str) -> Any:
    if value == "null":
        return None
    return value


def _render_scalar(value: Any) -> str:
    if value is None:
        return "null"
    return str(value)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
