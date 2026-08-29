"""
config.py — centralised configuration loader for resume-agent.

Reads values from a .env file (if present) and environment variables.
All other modules import from here — never read os.environ directly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of this file, or cwd)
_ENV_FILE = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=False)


@dataclass(frozen=True)
class Config:
    # ── Gemini ────────────────────────────────────────────────────────────────
    gemini_api_key: str
    gemini_model: str = "gemini-3.5-flash"

    # ── Storage ───────────────────────────────────────────────────────────────
    storage_backend: str = "sqlite"           # "sqlite" | "firestore"
    sqlite_db_path: Path = field(default_factory=lambda: Path("data/checkpoints.db"))
    gcp_project_id: str = ""                  # only needed for firestore

    # ── Watcher ───────────────────────────────────────────────────────────────
    repo_path: Path = field(default_factory=lambda: Path("."))
    log_file_path: Path | None = None         # shell history file to tail
    checkpoint_interval: int = 60             # seconds between snapshots

    # ── Watcher tuning ────────────────────────────────────────────────────────
    min_checkpoint_interval: int = 10         # never go below this
    max_checkpoint_interval: int = 300        # never go above this
    recent_commits_count: int = 5
    terminal_tail_lines: int = 50
    active_file_window_minutes: int = 5


def _resolve_log_path() -> Path | None:
    """Return the shell history path from env, or auto-detect."""
    raw = os.getenv("LOG_FILE_PATH", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.exists() else None

    # Auto-detect common locations
    candidates = [
        Path.home() / ".bash_history",
        Path.home() / ".zsh_history",
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_config() -> Config:
    """Build and validate the Config object from environment variables."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(
            "[config] ERROR: GEMINI_API_KEY is not set.\n"
            "  → Copy .env.example to .env and fill in your key.",
            file=sys.stderr,
        )
        # Don't hard-exit here so unit tests can still import the module;
        # callers that actually need the key will fail when they try to use it.

    raw_interval = os.getenv("CHECKPOINT_INTERVAL_DEFAULT", "60")
    try:
        interval = int(raw_interval)
    except ValueError:
        interval = 60

    repo_raw = os.getenv("REPO_PATH", ".").strip()
    repo_path = Path(repo_raw).expanduser().resolve()

    sqlite_path_raw = os.getenv("SQLITE_DB_PATH", "data/checkpoints.db").strip()
    sqlite_db_path = Path(sqlite_path_raw)
    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        gemini_api_key=api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip(),
        storage_backend=os.getenv("STORAGE_BACKEND", "sqlite").strip().lower(),
        sqlite_db_path=sqlite_db_path,
        gcp_project_id=os.getenv("GCP_PROJECT_ID", "").strip(),
        repo_path=repo_path,
        log_file_path=_resolve_log_path(),
        checkpoint_interval=interval,
    )


# Module-level singleton — import this in other modules.
cfg: Config = load_config()
