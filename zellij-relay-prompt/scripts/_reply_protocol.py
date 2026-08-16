#!/usr/bin/env python3
"""Shared implementation for the tracked delegation reply protocol.

The protocol deliberately has no zellij dependency.  A route is a private
directory in the system temporary directory.  ``reply.json`` is the durable
source of truth and ``wake.fifo`` is only an optimization for waking a waiter.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import select
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
ROUTE_PREFIX = "zellij-reply-route-"
REPLY_NAME = "reply.json"
WAKE_NAME = "wake.fifo"
STATE_LOCK_NAME = "state.lock"
WAITER_LOCK_NAME = "waiter.lock"
RESULT_NAME = "result.bin"
SUMMARY_LIMIT = 4096
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}
RECEIVER_STATUSES = {"succeeded", "failed"}


class ProtocolError(Exception):
    """An invalid request, route, record, or protocol operation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def temp_root(value: str | None = None) -> Path:
    root = Path(value) if value else Path(tempfile.gettempdir())
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ProtocolError(f"temporary directory is unavailable: {root}: {exc}") from exc
    if not root.is_dir():
        raise ProtocolError(f"temporary directory is not a directory: {root}")
    return root


def validate_request_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ProtocolError(f"invalid request_id: {value!r}") from exc
    canonical = str(parsed)
    if canonical != value:
        raise ProtocolError("request_id must be a canonical lowercase UUID")
    return canonical


def route_for(request_id: str, temp_dir: str | None = None) -> Path:
    request_id = validate_request_id(request_id)
    root = temp_root(temp_dir)
    route = root / f"{ROUTE_PREFIX}{request_id}"
    # Keep the route lookup constrained to one direct child of the selected
    # temporary directory.  Never accept a caller-provided path here.
    if route.parent != root or route.name != f"{ROUTE_PREFIX}{request_id}":
        raise ProtocolError("invalid reply route")
    try:
        info = route.lstat()
    except FileNotFoundError as exc:
        raise ProtocolError(f"reply route does not exist for {request_id}") from exc
    except OSError as exc:
        raise ProtocolError(f"cannot inspect reply route: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ProtocolError("reply route is not a directory")
    if route.is_symlink():
        raise ProtocolError("reply route must not be a symlink")
    try:
        metadata = json.loads((route / "request.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("reply route metadata is missing or invalid") from exc
    if metadata.get("schema_version") != SCHEMA_VERSION or metadata.get("request_id") != request_id:
        raise ProtocolError("reply route metadata does not match request_id")
    return route


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def create_route(temp_dir: str | None = None) -> dict[str, Any]:
    root = temp_root(temp_dir)
    for _ in range(10):
        request_id = str(uuid.uuid4())
        route = root / f"{ROUTE_PREFIX}{request_id}"
        try:
            route.mkdir(mode=0o700)
        except FileExistsError:
            continue
        try:
            os.chmod(route, 0o700)
            os.mkfifo(route / WAKE_NAME, 0o600)
            for lock_name in (STATE_LOCK_NAME, WAITER_LOCK_NAME):
                lock_fd = os.open(route / lock_name, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(lock_fd)
            atomic_write(
                route / "request.json",
                json.dumps(
                    {"schema_version": SCHEMA_VERSION, "request_id": request_id},
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            _fsync_directory(route)
            script_dir = Path(__file__).parent
            reply_script = (script_dir / "reply-to-request.py").resolve()
            wait_script = (script_dir / "wait-for-reply.py").resolve()
            cancel_script = (script_dir / "cancel-reply.py").resolve()
            return {
                "schema_version": SCHEMA_VERSION,
                "request_id": request_id,
                "route_dir": str(route),
                "wait_command": f"python3 {wait_script} {request_id}",
                "reply_command": f"python3 {reply_script} {request_id} <succeeded|failed> <summary-file> [result-file]",
                "cancel_command": f"python3 {cancel_script} {request_id}",
            }
        except BaseException:
            # The directory is unique and private; leave it intact on an
            # unexpected setup failure so diagnostics are not lost.
            raise
    raise ProtocolError("could not allocate a unique request_id")


def _record_path(route: Path) -> Path:
    return route / REPLY_NAME


def _validate_record(record: Any, route: Path) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ProtocolError("reply record is not a JSON object")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unsupported reply record schema_version")
    request_id = record.get("request_id")
    if not isinstance(request_id, str):
        raise ProtocolError("reply record request_id is invalid")
    validate_request_id(request_id)
    expected = route.name.removeprefix(ROUTE_PREFIX)
    if request_id != expected:
        raise ProtocolError("reply record request_id does not match route")
    status = record.get("status")
    if status not in TERMINAL_STATUSES:
        raise ProtocolError("reply record status is invalid")
    summary = record.get("summary")
    if not isinstance(summary, str) or len(summary.encode("utf-8")) > SUMMARY_LIMIT:
        raise ProtocolError("reply record summary exceeds 4 KiB or is invalid")
    result_file = record.get("result_file")
    if result_file is not None:
        if not isinstance(result_file, str):
            raise ProtocolError("reply record result_file is invalid")
        result_path = Path(result_file)
        try:
            if result_path.resolve(strict=False).parent != route.resolve(strict=True):
                raise ProtocolError("reply record result_file escapes route")
            info = result_path.lstat()
        except OSError as exc:
            raise ProtocolError("reply record result_file is inaccessible") from exc
        if not stat.S_ISREG(info.st_mode) or result_path.is_symlink():
            raise ProtocolError("reply record result_file is not a regular route file")
    if not isinstance(record.get("finished_at"), str):
        raise ProtocolError("reply record finished_at is invalid")
    if not isinstance(record.get("content_sha256"), str):
        raise ProtocolError("reply record content_sha256 is missing")
    return record


def read_record(route: Path) -> dict[str, Any] | None:
    path = _record_path(route)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProtocolError(f"cannot read reply record: {exc}") from exc
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("reply record is not valid UTF-8 JSON") from exc
    return _validate_record(record, route)


def content_hash(request_id: str, status: str, summary: str, result: bytes | None) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "summary": summary,
        "result_sha256": hashlib.sha256(result).hexdigest() if result is not None else None,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_record(request_id: str, status: str, summary: str, result: bytes | None, result_file: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "summary": summary,
        "result_file": result_file,
        "finished_at": utc_now(),
        "content_sha256": content_hash(request_id, status, summary, result),
    }


def records_match(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return existing.get("content_sha256") == candidate.get("content_sha256")


@contextmanager
def state_lock(route: Path) -> Iterator[None]:
    path = route / STATE_LOCK_NAME
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise ProtocolError(f"cannot open route state lock: {exc}") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    except OSError as exc:
        raise ProtocolError(f"route state lock failed: {exc}") from exc
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextmanager
def waiter_lock(route: Path) -> Iterator[None]:
    path = route / WAITER_LOCK_NAME
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise ProtocolError(f"cannot open waiter lock: {exc}") from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProtocolError("a reply waiter is already running") from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def commit_record(route: Path, candidate: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Commit candidate under the state lock; return (authoritative, wrote)."""
    with state_lock(route):
        existing = read_record(route)
        if existing is not None:
            return existing, False
        atomic_write(
            _record_path(route),
            json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        return candidate, True


def wake(route: Path) -> None:
    try:
        fd = os.open(route / WAKE_NAME, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno in (errno.ENXIO, errno.ENOENT, errno.EAGAIN):
            return
        return
    try:
        try:
            os.write(fd, b"1")
        except OSError:
            pass
    finally:
        os.close(fd)


def read_result(source: str | None) -> bytes | None:
    if source is None:
        return None
    source_path = Path(source)
    try:
        info = source_path.lstat()
    except OSError as exc:
        raise ProtocolError(f"cannot read result file {source}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or source_path.is_symlink():
        raise ProtocolError("result_file must be a regular, non-symlink file")
    try:
        data = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolError(f"cannot read result file {source}: {exc}") from exc
    return data


def write_result(route: Path, data: bytes) -> str:
    destination = route / RESULT_NAME
    atomic_write(destination, data)
    return str(destination)


def copy_result(route: Path, source: str | None) -> tuple[bytes | None, str | None]:
    data = read_result(source)
    if data is None:
        return None, None
    return data, write_result(route, data)


def finish(route: Path, request_id: str, status: str, summary: str, result: bytes | None, result_file: str | None) -> tuple[dict[str, Any], bool]:
    candidate = make_record(request_id, status, summary, result, result_file)
    record, wrote = commit_record(route, candidate)
    if wrote:
        wake(route)
    return record, wrote


def wait_for_record(route: Path, request_id: str, timeout: float | None) -> dict[str, Any]:
    started = time.monotonic()
    with waiter_lock(route):
        record = read_record(route)
        if record is not None:
            return record
        try:
            fd = os.open(route / WAKE_NAME, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            raise ProtocolError(f"cannot open reply wake FIFO: {exc}") from exc
        try:
            # Recheck after opening the FIFO to close the commit/wakeup race.
            record = read_record(route)
            if record is not None:
                return record
            while True:
                remaining = None if timeout is None else timeout - (time.monotonic() - started)
                if remaining is not None and remaining <= 0:
                    record, _ = finish(route, request_id, "timed_out", "Reply waiter timed out.", None, None)
                    return record
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    record, _ = finish(route, request_id, "timed_out", "Reply waiter timed out.", None, None)
                    return record
                try:
                    os.read(fd, 4096)
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                        raise
                record = read_record(route)
                if record is not None:
                    return record
        finally:
            os.close(fd)


def read_summary(path: str) -> str:
    try:
        data = read_result(path)
    except ProtocolError as exc:
        raise ProtocolError(f"cannot read summary file {path}: {exc}") from exc
    if data is None:
        raise ProtocolError(f"cannot read summary file {path}")
    if len(data) > SUMMARY_LIMIT:
        raise ProtocolError("summary must be at most 4 KiB UTF-8")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("summary must be valid UTF-8") from exc


def output_record(record: dict[str, Any]) -> None:
    print(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
