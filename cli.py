"""
cli.py — command-line entry point for resume-agent.

Usage:
    python cli.py --watch                 Start background watcher (blocking)
    python cli.py --interrupt              Capture a checkpoint right now
    python cli.py --resume                 Surface latest checkpoint + clarify
    python cli.py --status                 Show interruption statistics table
    python cli.py --history                Browse past checkpoints
    python cli.py --setup                  Interactive first-time setup wizard
    python cli.py --interrupt --repo PATH  Point at a project without editing .env
    python cli.py --help                   Show this help message

The orchestrator (main.py) does all the real work; this module is
a thin CLI wrapper using argparse + rich.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# ── Windows Unicode fix: reconfigure stdout to UTF-8 before any output ────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Python 3.7+
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.text import Text
from rich.prompt import Prompt, Confirm

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────

_BANNER = r"""
  ██████╗ ███████╗███████╗██╗   ██╗███╗   ███╗███████╗
  ██╔══██╗██╔════╝██╔════╝██║   ██║████╗ ████║██╔════╝
  ██████╔╝█████╗  ███████╗██║   ██║██╔████╔██║█████╗
  ██╔══██╗██╔══╝  ╚════██║██║   ██║██║╚██╔╝██║██╔══╝
  ██║  ██║███████╗███████║╚██████╔╝██║ ╚═╝ ██║███████╗
  ╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝
  ──────────────── Agent ────────────────────────────
  Never lose your train of thought again.
"""


def _print_banner() -> None:
    console.print(Text(_BANNER, style="bold cyan"))


# ─────────────────────────────────────────────────────────────────────────────
# Setup wizard — writes .env interactively, no manual file editing needed
# ─────────────────────────────────────────────────────────────────────────────

def run_setup_wizard() -> None:
    """
    Interactive first-time setup: prompts for the essentials and writes
    a .env file in the project root. Safe to re-run — existing values are
    shown as defaults so you can just press Enter to keep them.
    """
    env_path = Path(__file__).parent / ".env"

    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            existing[key.strip()] = value.strip()

    console.rule("[bold cyan]resume-agent — Setup[/bold cyan]")
    console.print("Answer a few questions to get started. Press Enter to keep the current value.\n")

    existing_key = existing.get("GEMINI_API_KEY", "")
    if existing_key:
        console.print(f"  [dim]Current key ends in ...{existing_key[-4:]}[/dim]")
        keep_key = Confirm.ask("  Keep this key?", default=True, console=console)
    else:
        keep_key = False

    if keep_key:
        api_key = existing_key
    else:
        api_key = Prompt.ask(
            "  Gemini API key (from aistudio.google.com/apikey)",
            default="",
            console=console,
            password=True,
            show_default=False,
        )

    model = Prompt.ask(
        "  Gemini model",
        default=existing.get("GEMINI_MODEL", "gemini-3.5-flash"),
        console=console,
    )

    repo_path = Prompt.ask(
        "  Path to the project you want the agent to watch",
        default=existing.get("REPO_PATH", "."),
        console=console,
    )

    storage_backend = Prompt.ask(
        "  Storage backend",
        default=existing.get("STORAGE_BACKEND", "sqlite"),
        choices=["sqlite", "firestore"],
        console=console,
    )

    gcp_project_id = existing.get("GCP_PROJECT_ID", "")
    if storage_backend == "firestore":
        gcp_project_id = Prompt.ask(
            "  Google Cloud / Firebase project ID",
            default=gcp_project_id,
            console=console,
        )

    sqlite_db_path = Prompt.ask(
        "  SQLite database path",
        default=existing.get("SQLITE_DB_PATH", "data/checkpoints.db"),
        console=console,
    )

    log_file_path = Prompt.ask(
        "  Terminal/shell history file to tail (leave blank to auto-detect)",
        default=existing.get("LOG_FILE_PATH", ""),
        console=console,
    )

    checkpoint_interval = Prompt.ask(
        "  Default checkpoint interval, in seconds",
        default=existing.get("CHECKPOINT_INTERVAL_DEFAULT", "60"),
        console=console,
    )

    lines = [
        "GEMINI_API_KEY=" + api_key,
        "GEMINI_MODEL=" + model,
        "",
        "# Storage backend: sqlite or firestore",
        "STORAGE_BACKEND=" + storage_backend,
        "SQLITE_DB_PATH=" + sqlite_db_path,
        "GCP_PROJECT_ID=" + gcp_project_id,
        "",
        "# Project to watch (override per-run with --repo PATH)",
        "REPO_PATH=" + repo_path,
        "",
        "# Terminal/shell history file for context tailing",
        "LOG_FILE_PATH=" + log_file_path,
        "",
        "# How often the watcher polls for changes, in seconds",
        "CHECKPOINT_INTERVAL_DEFAULT=" + checkpoint_interval,
        "",
    ]

    if env_path.exists():
        if not Confirm.ask(f"\n  Overwrite existing {env_path}?", default=True, console=console):
            console.print("[dim]Setup cancelled — no changes written.[/dim]")
            return

    env_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"\n[green]Saved configuration to {env_path}[/green]")
    console.print("[dim]You can re-run `python cli.py --setup` any time to change these.[/dim]\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLI parser
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-agent",
        description=(
            "resume-agent — autonomous developer context checkpointing.\n"
            "Watches your work, captures context on interruption, and\n"
            "helps you resume instantly with AI-powered summaries.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py --setup                          # first-time setup wizard
  python cli.py --watch                           # start background watcher
  python cli.py --interrupt                       # checkpoint now
  python cli.py --interrupt --repo "D:\\my-project" # checkpoint a different project
  python cli.py --resume                          # resume after being interrupted
  python cli.py --status                          # view interruption stats
  python cli.py --history                         # browse past checkpoints
        """,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--setup",
        action="store_true",
        help="Interactive first-time setup wizard — writes .env for you.",
    )
    mode.add_argument(
        "--watch",
        action="store_true",
        help="Start the background watcher (blocking — keep in a separate terminal).",
    )
    mode.add_argument(
        "--interrupt",
        action="store_true",
        help="Capture a checkpoint of current work context right now.",
    )
    mode.add_argument(
        "--resume",
        action="store_true",
        help="Surface the latest checkpoint and optionally clarify its task type.",
    )
    mode.add_argument(
        "--status",
        action="store_true",
        help="Show a table of interruption statistics per task type.",
    )
    mode.add_argument(
        "--history",
        action="store_true",
        help="Browse the most recent checkpoints (not just the latest).",
    )

    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help=(
            "Path to the project to watch, overriding REPO_PATH in .env for "
            "this run only. Lets you point at a different project without "
            "editing config files."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="With --history: number of past checkpoints to show (default: 10).",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        default=False,
        help=(
            "With --interrupt: take a one-shot snapshot without starting the "
            "background watcher first. Useful for scripted / hotkey invocations."
        ),
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Skip the clarifying question (useful for CI or scripted flows).",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        default=False,
        help="Suppress the banner.",
    )

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.quiet:
        _print_banner()

    # Setup wizard doesn't need config to already be valid — handle it first,
    # before touching anything that reads GEMINI_API_KEY etc.
    if args.setup:
        run_setup_wizard()
        return

    # Late import so startup is fast for --help and --setup
    from main import ResumeAgentOrchestrator

    orch = ResumeAgentOrchestrator(repo_path=args.repo)

    try:
        if args.watch:
            orch.watch()  # blocking

        elif args.interrupt:
            if not args.no_watch:
                # Start watcher so we get a properly-warmed-up snapshot
                orch.start_watcher()
            result = orch.interrupt(non_interactive=args.non_interactive)
            if result is None:
                sys.exit(0)

        elif args.resume:
            orch.resume(non_interactive=args.non_interactive)

        elif args.status:
            orch.status()

        elif args.history:
            orch.history(limit=args.limit)

    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted. Goodbye.[/dim]")
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        if not args.quiet:
            console.print_exception()
        sys.exit(1)
    finally:
        orch.stop()


if __name__ == "__main__":
    main()