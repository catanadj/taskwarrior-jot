from __future__ import annotations

import fcntl
import errno
import os
import tempfile
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


FrontMatter = OrderedDict[str, Any]


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
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if exc.errno != errno.ENOSYS:
                raise
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
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_dir.rmdir()
        except FileNotFoundError:
            pass


@contextmanager
def locked_document(path: Path) -> Iterator[tuple[FrontMatter, str]]:
    """Lock a note across a complete read-modify-write transaction."""
    with exclusive_file_lock(path):
        yield read_document(path)


def parse_document(text: str) -> tuple[FrontMatter, str]:
    lines = str(text or "").splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return OrderedDict(), str(text or "")

    metadata: FrontMatter = OrderedDict()
    idx = 1
    current_key: str | None = None
    current_list: list[str] = []

    while idx < len(lines):
        line = lines[idx]
        idx += 1
        if line.strip() == "---":
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

    if current_key is not None:
        metadata[current_key] = list(current_list)

    body_lines = lines[idx:]
    body = "\n".join(body_lines)
    if str(text or "").endswith("\n"):
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
