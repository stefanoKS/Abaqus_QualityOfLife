"""Cross-process, lifetime-held ownership of one Abaqus QOL data directory.

The database and artifact tree are shared mutable state. Two API/worker pairs
pointed at the same directory can interleave queue claims and artifact writes, so
ownership must be decided by the operating system, not by a read-then-write JSON
record (which two cold starts can both win).

Two OS-level locks are used:

``owner.lock``
    Held by the launcher/API process for the whole running lifetime. The lock is
    released by the kernel when the process exits, including a crash, so a stale
    PID can never be mistaken for a live owner.

``worker.lock``
    Held by the worker process. A supervisor crash can leave an orphaned worker
    operating on the directory; an owner that finds this lock held refuses to
    start (fail closed) instead of running a second worker beside it.

``instance.json`` remains the human/diagnostic record (PID, port, release,
worker PID and start times). It is written *after* the lock is acquired and is
never the sole synchronization mechanism.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

OWNER_LOCK = "owner.lock"
WORKER_LOCK = "worker.lock"
INSTANCE_RECORD = "instance.json"

OWNER = "owner"
WORKER = "worker"


class OwnershipConflict(RuntimeError):
    """The directory is owned, or its state cannot be established safely."""


def canonical_identity(root):
    """Stable identity for a data directory, including its filesystem object."""
    path = Path(root).resolve()
    try:
        info = path.stat()
        raw = f"{str(path).casefold()}|{info.st_dev}:{info.st_ino}"
    except OSError:
        raw = str(path).casefold()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _lock_fd(fd):
    """Take a non-blocking exclusive lock on one byte of an open file."""
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock_fd(fd):
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


class FileLock:
    """A one-byte OS lock held on an open file descriptor."""

    def __init__(self, path):
        self.path = Path(path)
        self.fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            # Windows byte-range locking needs a byte to exist; writing the same
            # byte from two contenders before locking is harmless.
            try:
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                    os.fsync(fd)
            except OSError:
                pass
            if not _lock_fd(fd):
                os.close(fd)
                return False
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self):
        if self.fd is None:
            return
        _unlock_fd(self.fd)
        try:
            os.close(self.fd)
        finally:
            self.fd = None


class _Held:
    def __init__(self, lock, record, root):
        self.lock = lock
        self.record = record
        self.root = root
        self.refs = 1


_HELD: dict[tuple[str, str], _Held] = {}


def _instance_path(root):
    return Path(root) / INSTANCE_RECORD


def read_instance(root):
    try:
        return json.loads(_instance_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_instance(root, record):
    """Atomically replace the diagnostic record."""
    path = _instance_path(root)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def worker_is_alive(record, root):
    """True when the recorded worker PID is alive and belongs to this data root.

    Process identity is checked as well as existence, so a reused PID is not
    mistaken for the application's worker.
    """
    pid = record.get("worker_pid") if record else None
    if not pid:
        return False
    try:
        import psutil

        process = psutil.Process(int(pid))
        command = " ".join(process.cmdline())
    except ImportError:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return False
        return True
    except Exception:
        return False
    return "services.worker" in command and str(root) in command


def _describe_owner(record, root):
    if not record or not record.get("pid"):
        return (
            f"the data directory {root} is already owned by another Abaqus QOL process "
            "(its metadata was not readable). Nothing was stopped."
        )
    parts = [f"PID {record.get('pid')}"]
    if record.get("port"):
        parts.append(f"port {record.get('port')}")
    if record.get("release"):
        parts.append(f"release {record.get('release')}")
    return (
        f"the data directory {root} is already owned by Abaqus QOL "
        + ", ".join(parts)
        + ". Nothing was stopped."
    )


def acquire(root, role, pid, port=0, release_id=""):
    """Acquire ``owner`` or ``worker`` ownership, safely re-entrant in-process.

    Returns the diagnostic record. Raises :class:`OwnershipConflict` when owned,
    when an unreconciled worker exists, or when the lock cannot be established.
    """
    root = Path(root).resolve()
    key = (str(root), role)
    held = _HELD.get(key)
    if held is not None:
        recorded = held.record.get("pid") if role == OWNER else held.record.get("worker_pid")
        if recorded is not None and int(recorded) != int(pid):
            raise OwnershipConflict(
                f"the data directory {root} is already owned by Abaqus QOL PID {recorded} "
                f"({role} role); PID {pid} cannot share it. Nothing was stopped."
            )
        held.refs += 1
        return held.record

    record = read_instance(root) or {}
    if role == OWNER:
        lock = FileLock(root / OWNER_LOCK)
        if not lock.acquire():
            # The winner may have written its metadata since our first read.
            raise OwnershipConflict(
                _describe_owner(read_instance(root), root)
                + " Use one port for this data directory, or set a separate SEAL_DATA "
                "for an independent instance."
            )
        # An API may attach to a worker that is already running (the supported
        # independent API/worker workflow). The launcher separately checks the
        # worker lock before spawning a *new* worker; see worker_lock_free().
        # Keep a diagnostic worker PID only when the worker lock is actually
        # held; the lock, not the PID record, decides ownership.
        existing_worker = (
            record.get("worker_pid") if not worker_lock_free(root) else None
        )
        record = {
            "pid": int(pid),
            "port": int(port),
            "release": release_id,
            "started": time.time(),
            "data": canonical_identity(root),
            "worker_pid": existing_worker,
            "role": OWNER,
        }
    else:
        lock = FileLock(root / WORKER_LOCK)
        if not lock.acquire():
            raise OwnershipConflict(
                f"Another worker already owns the data directory {root}. "
                "Nothing was stopped."
            )
        record = {
            **record,
            "worker_pid": int(pid),
            "worker_started": time.time(),
            "worker_data": canonical_identity(root),
        }
        record.setdefault("role", WORKER)

    try:
        _write_instance(root, record)
    except OSError:
        lock.release()
        raise
    _HELD[key] = _Held(lock, record, root)
    return record


def release(root, role, pid):
    """Release one in-process reference; the OS lock drops at the last one.

    The worker fields in ``instance.json`` are cleared only by the owning worker,
    so a diagnostics record never claims a worker that already exited.
    """
    root = Path(root).resolve()
    key = (str(root), role)
    held = _HELD.get(key)
    if held is None:
        return
    held.refs -= 1
    if held.refs > 0:
        return
    del _HELD[key]
    try:
        record = read_instance(root) or {}
        if role == WORKER and int(record.get("worker_pid") or 0) == int(pid):
            record["worker_pid"] = None
            record["worker_stopped"] = time.time()
            _write_instance(root, record)
        elif role == OWNER and int(record.get("pid") or 0) == int(pid):
            record["pid"] = None
            record["stopped"] = time.time()
            _write_instance(root, record)
    except (OSError, ValueError):
        pass
    held.lock.release()


def worker_lock_free(root):
    """True when no worker process currently holds this data directory."""
    probe = FileLock(Path(root) / WORKER_LOCK)
    if not probe.acquire():
        return False
    probe.release()
    return True


def held(root, role):
    return (str(Path(root).resolve()), role) in _HELD


def reset_for_tests():
    """Drop in-process handles without touching files (test isolation only)."""
    for key in list(_HELD):
        _HELD[key].lock.release()
        del _HELD[key]


def process_identity():
    return f"{os.getpid()}@{sys.platform}"
