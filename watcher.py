"""
watcher.py — background observer that continuously snapshots developer context.

No LLM calls here — this is pure Python. It runs in a daemon thread and puts
WorkSnapshot objects into a thread-safe queue for the orchestrator to consume.

Key functions (also exported as ADK tools in checkpoint_agent.py):
    get_git_diff(repo_path)        → str
    get_recent_commits(repo_path)  → list[str]
    get_terminal_tail(log_path)    → str
    get_active_files(repo_path)    → list[str]
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from config import cfg

# gitpython is listed in requirements.txt
try:
    import git  # type: ignore
    _GIT_AVAILABLE = True
except ImportError:
    _GIT_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WorkSnapshot:
    """A point-in-time snapshot of the developer's working context."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    git_diff: str = ""               # staged + unstaged diff text
    recent_commits: list[str] = field(default_factory=list)  # last N commit messages
    terminal_tail: str = ""          # last N lines of shell history
    active_files: list[str] = field(default_factory=list)    # recently modified paths
    repo_path: str = "."             # which repo was watched

    def is_empty(self) -> bool:
        """True if there is no meaningful context to checkpoint."""
        return (
            not self.git_diff.strip()
            and not self.recent_commits
            and not self.active_files
        )

    def to_context_string(self) -> str:
        """Format the snapshot as a human-readable string for the LLM prompt."""
        parts: list[str] = []
        parts.append(f"=== Snapshot @ {self.timestamp.isoformat()} ===\n")

        if self.git_diff.strip():
            diff_excerpt = self.git_diff[:4000]  # keep prompt size sane
            if len(self.git_diff) > 4000:
                diff_excerpt += "\n... [diff truncated]"
            parts.append(f"--- Git Diff (staged + unstaged) ---\n{diff_excerpt}\n")
        else:
            parts.append("--- Git Diff ---\n(no changes)\n")

        if self.recent_commits:
            commits_str = "\n".join(f"  • {c}" for c in self.recent_commits)
            parts.append(f"--- Recent Commits ---\n{commits_str}\n")
        else:
            parts.append("--- Recent Commits ---\n(none)\n")

        if self.active_files:
            files_str = "\n".join(f"  • {f}" for f in self.active_files)
            parts.append(f"--- Recently Modified Files ---\n{files_str}\n")

        if self.terminal_tail.strip():
            tail_excerpt = self.terminal_tail[-2000:]  # last 2000 chars
            parts.append(f"--- Terminal History (tail) ---\n{tail_excerpt}\n")

        return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot functions (pure, no side effects — easy to unit-test)
# ─────────────────────────────────────────────────────────────────────────────

def get_git_diff(repo_path: str | Path | None = None) -> str:
    """
    Return the combined staged + unstaged git diff for the repo at `repo_path`.

    Returns an empty string if gitpython is unavailable, the path is not a
    git repo, or there are no changes.
    """
    if not _GIT_AVAILABLE:
        return "[gitpython not installed — install with: pip install gitpython]"

    path = Path(repo_path or cfg.repo_path).resolve()
    try:
        repo = git.Repo(path, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        return f"[{path} is not a git repository]"
    except Exception as exc:
        return f"[git error: {exc}]"

    try:
        # Unstaged changes (working tree vs index)
        unstaged = repo.git.diff()
        # Staged changes (index vs HEAD)
        staged = repo.git.diff("--cached")
        combined = "\n".join(filter(None, [staged, unstaged]))
        return combined or "(no changes in working tree or index)"
    except Exception as exc:
        return f"[git diff error: {exc}]"


def get_recent_commits(
    repo_path: str | Path | None = None,
    n: int | None = None,
) -> list[str]:
    """
    Return the last `n` commit messages (one-liners) for the repo at `repo_path`.

    Returns an empty list if gitpython is unavailable or there are no commits.
    """
    if not _GIT_AVAILABLE:
        return []

    n = n or cfg.recent_commits_count
    path = Path(repo_path or cfg.repo_path).resolve()
    try:
        repo = git.Repo(path, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        return []
    except Exception:
        return []

    try:
        commits = list(repo.iter_commits(max_count=n))
        return [
            f"{c.hexsha[:7]} {c.summary} ({_relative_time(c.committed_datetime)})"
            for c in commits
        ]
    except Exception:
        return []


def get_terminal_tail(
    log_path: str | Path | None = None,
    lines: int | None = None,
) -> str:
    """
    Return the last `lines` lines from the shell history file at `log_path`.

    Gracefully returns an empty string if the file doesn't exist or can't be read.
    """
    n = lines or cfg.terminal_tail_lines
    path = log_path or cfg.log_file_path
    if path is None:
        return "(no terminal log file configured or auto-detected)"

    path = Path(path).expanduser()
    if not path.exists():
        return f"(log file not found: {path})"

    try:
        # Efficient tail: read last N lines without loading the whole file
        with open(path, "rb") as f:
            # Seek to end, then walk backwards counting newlines
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return "(log file is empty)"

            block_size = 4096
            data = b""
            newlines_found = 0
            pos = size

            while pos > 0 and newlines_found <= n:
                read_size = min(block_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                data = chunk + data
                newlines_found = data.count(b"\n")

        tail_lines = data.decode("utf-8", errors="replace").splitlines()[-n:]
        return "\n".join(tail_lines)
    except PermissionError:
        return f"(permission denied reading: {path})"
    except Exception as exc:
        return f"(error reading terminal log: {exc})"


_EXCLUDED_DIR_NAMES = {"data", "__pycache__", "node_modules", ".venv", "venv", ".git"}


def get_active_files(
    repo_path: str | Path | None = None,
    minutes: int | None = None,
) -> list[str]:
    """
    Return paths of files modified within the last `minutes` minutes in `repo_path`.

    Walks the directory tree and checks mtime. Skips hidden dirs, .git, and
    known noise directories (data/, __pycache__, node_modules, venvs) so the
    tool's own database writes don't get mistaken for developer activity.
    """
    minutes = minutes or cfg.active_file_window_minutes
    base = Path(repo_path or cfg.repo_path).resolve()
    cutoff = datetime.now().timestamp() - (minutes * 60)
    active: list[str] = []

    try:
        for p in base.rglob("*"):
            # Skip hidden dirs and .git
            if any(part.startswith(".") for part in p.parts):
                continue
            if any(part in _EXCLUDED_DIR_NAMES for part in p.parts):
                continue
            if p.is_file():
                try:
                    if p.stat().st_mtime > cutoff:
                        active.append(str(p.relative_to(base)))
                except OSError:
                    pass
    except Exception:
        pass

    return sorted(active)


# ─────────────────────────────────────────────────────────────────────────────
# Background watcher thread
# ─────────────────────────────────────────────────────────────────────────────

class WatcherThread(threading.Thread):
    """
    Daemon thread that periodically captures a WorkSnapshot and puts it into
    `snapshot_queue`.

    The orchestrator (main.py) reads from the queue. The interval can be
    updated at runtime via `set_interval()` — this is how adaptive
    checkpointing works.

    Usage:
        q = queue.Queue(maxsize=1)   # only keep the latest snapshot
        watcher = WatcherThread(interval=60, snapshot_queue=q)
        watcher.start()
        ...
        snapshot = q.get()           # blocks until a snapshot is ready
    """

    def __init__(
        self,
        interval: int | None = None,
        snapshot_queue: queue.Queue | None = None,
        repo_path: str | Path | None = None,
        log_file_path: str | Path | None = None,
    ) -> None:
        super().__init__(name="WatcherThread", daemon=True)
        self._interval = interval or cfg.checkpoint_interval
        self._queue: queue.Queue = snapshot_queue or queue.Queue(maxsize=1)
        self._repo_path = repo_path or cfg.repo_path
        self._log_file_path = log_file_path or cfg.log_file_path
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def queue(self) -> queue.Queue:
        return self._queue

    @property
    def interval(self) -> int:
        with self._lock:
            return self._interval

    def set_interval(self, seconds: int) -> None:
        """Update the polling interval at runtime (adaptive checkpointing)."""
        clamped = max(cfg.min_checkpoint_interval, min(seconds, cfg.max_checkpoint_interval))
        with self._lock:
            self._interval = clamped

    def stop(self) -> None:
        """Signal the thread to stop after its current sleep."""
        self._stop_event.set()

    def capture_now(self) -> WorkSnapshot:
        """Manually capture a snapshot (called on --interrupt regardless of interval)."""
        return self._take_snapshot()

    # ── Thread body ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Poll continuously until stop() is called."""
        while not self._stop_event.is_set():
            snapshot = self._take_snapshot()
            # Overwrite old snapshot — we only care about the latest
            try:
                self._queue.get_nowait()  # discard previous if queue is full
            except queue.Empty:
                pass
            self._queue.put(snapshot)

            # Sleep in short increments so stop() is responsive
            with self._lock:
                sleep_total = self._interval
            elapsed = 0
            while elapsed < sleep_total and not self._stop_event.is_set():
                time.sleep(min(1, sleep_total - elapsed))
                elapsed += 1

    def _take_snapshot(self) -> WorkSnapshot:
        """Collect all context signals and return a WorkSnapshot."""
        return WorkSnapshot(
            timestamp=datetime.now(timezone.utc),
            git_diff=get_git_diff(self._repo_path),
            recent_commits=get_recent_commits(self._repo_path),
            terminal_tail=get_terminal_tail(self._log_file_path),
            active_files=get_active_files(self._repo_path),
            repo_path=str(self._repo_path),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _relative_time(dt: datetime) -> str:
    """Return a human-readable relative time string (e.g. '3 minutes ago')."""
    now = datetime.now(tz=dt.tzinfo or timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    elif seconds < 3600:
        return f"{seconds // 60}m ago"
    elif seconds < 86400:
        return f"{seconds // 3600}h ago"
    else:
        return f"{seconds // 86400}d ago"
