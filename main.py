"""
main.py — orchestrator for resume-agent.

Coordinates:
  • WatcherThread  — continuous background snapshot polling
  • checkpoint_agent — Gemini-powered context analysis
  • pattern_store  — persistent checkpoint + stats storage
  • clarify        — interactive clarifying question

Entry points (called by cli.py):
  interrupt(elapsed_since_last)  → checkpoint current context
  resume()                       → surface + confirm latest checkpoint
  status()                       → print interruption stats
  watch()                        → start background watcher (blocking)
"""

from __future__ import annotations

import queue
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

from config import cfg
from watcher import WatcherThread, WorkSnapshot
from checkpoint_agent import run_checkpoint_agent, CheckpointResult
from pattern_store import get_storage_backend, StorageBackend
from clarify import ask_clarifying_question, display_resume_summary

import io
console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class ResumeAgentOrchestrator:
    """
    Central coordinator that owns the watcher thread and storage backend.

    Typical lifecycle:
        orch = ResumeAgentOrchestrator()
        orch.start_watcher()          # starts background polling
        ...
        orch.interrupt()              # when developer is interrupted
        ...
        orch.resume()                 # when developer returns
        orch.stop()                   # graceful shutdown
    """

    def __init__(self, repo_path: str | Path | None = None) -> None:
        """
        Args:
            repo_path: Optional override for the repo to watch, taking
                       precedence over REPO_PATH in .env for this run only.
                       Lets you point the tool at a different project without
                       editing config files, e.g.:
                           python cli.py --interrupt --repo "D:\\some-project"
        """
        self._repo_path: Path = Path(repo_path).resolve() if repo_path else cfg.repo_path
        self._store: StorageBackend = get_storage_backend()
        self._snapshot_queue: queue.Queue = queue.Queue(maxsize=1)
        self._watcher: WatcherThread = WatcherThread(
            interval=cfg.checkpoint_interval,
            snapshot_queue=self._snapshot_queue,
            repo_path=self._repo_path,
        )
        self._running: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start_watcher(self) -> None:
        """Start the background watcher thread."""
        if not self._running:
            self._watcher.start()
            self._running = True
            console.print(
                f"[dim]Watcher started (interval: {self._watcher.interval}s, "
                f"repo: {self._repo_path})[/dim]"
            )

    def stop(self) -> None:
        """Gracefully stop the background watcher thread."""
        if self._running:
            self._watcher.stop()
            self._running = False

    # ── Core operations ───────────────────────────────────────────────────────

    def interrupt(self, *, non_interactive: bool = False) -> CheckpointResult | None:
        """
        Capture a checkpoint of the current work context.

        1. Grab the latest snapshot (either from the queue or captured fresh).
        2. Call the checkpoint agent to analyse it.
        3. Persist the checkpoint to storage.
        4. Update interruption stats and adaptive interval.

        Args:
            non_interactive: If True, skip clarifying question (for scripting).

        Returns:
            The CheckpointResult, or None if there's nothing to checkpoint.
        """
        console.print("\n[bold cyan]>> Interruption detected -- capturing context...[/bold cyan]")

        # Grab snapshot — fresh capture takes priority over queued one
        if self._running:
            snapshot = self._watcher.capture_now()
        else:
            snapshot = self._take_fresh_snapshot()

        if snapshot.is_empty():
            console.print("[yellow]No meaningful context to checkpoint (no git changes, no recent files).[/yellow]")
            return None

        # Elapsed time since the PREVIOUS checkpoint, read from storage.
        # (Works across separate CLI invocations — in-memory state resets
        # every time `python cli.py` runs as a fresh process.)
        now_wall = time.time()
        previous_time = self._store.get_previous_checkpoint_time()
        elapsed: float | None = None
        if previous_time is not None:
            elapsed = now_wall - previous_time

        # Run the checkpoint agent
        console.print("[dim]Analysing context with Gemini...[/dim]")
        feedback_history = self._store.get_recent_feedback(limit=10)
        result = run_checkpoint_agent(snapshot, feedback_history=feedback_history)

        # Persist
        checkpoint_id = self._store.save_checkpoint(
            summary=result.summary,
            task_type=result.task_type,
            confidence=result.confidence,
            next_likely_step=result.next_likely_step,
            raw_diff=snapshot.git_diff,
            elapsed_seconds=elapsed,
        )

        # Update stats + adaptive interval
        if elapsed is not None:
            self._store.update_interval(result.task_type, elapsed)
            self._adapt_interval(result.task_type)

        console.print(
            f"[green]>> Checkpoint saved[/green] "
            f"[dim](type: {result.task_type}, confidence: {int(result.confidence*100)}%)[/dim]"
        )

        # Display the result
        display_resume_summary(result)

        return result

    def resume(self, *, non_interactive: bool = False) -> None:
        """
        Surface the latest checkpoint and ask a clarifying question.

        Displays the resume summary and then invites the developer to confirm
        or correct the inferred task_type (the Collaborative Partner loop).
        """
        checkpoint = self._store.get_latest_checkpoint()
        if checkpoint is None:
            console.print("[yellow]No checkpoints found. Run --interrupt first to save context.[/yellow]")
            return

        # Reconstruct CheckpointResult from stored data
        result = CheckpointResult(
            summary=checkpoint.get("summary", ""),
            task_type=checkpoint.get("task_type", "unclear"),
            confidence=checkpoint.get("confidence", 0.5),
            next_likely_step=checkpoint.get("next_likely_step", ""),
        )

        # Show when this was saved
        ts_str = checkpoint.get("timestamp", "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                console.print(
                    f"\n[dim]Last checkpoint: {ts.strftime('%Y-%m-%d %H:%M:%S')} UTC[/dim]"
                )
            except ValueError:
                pass

        # Display summary panel
        display_resume_summary(result)

        # Ask clarifying question (the collaborative partner step)
        checkpoint_id = checkpoint.get("id", "")
        if checkpoint_id and not non_interactive:
            ask_clarifying_question(
                checkpoint_id=checkpoint_id,
                result=result,
                store=self._store,
                skip=False,
            )

    def status(self) -> None:
        """
        Print a rich table of interruption statistics per task_type.

        Shows how often each task type gets interrupted, average time before
        interruption, and the recommended checkpoint interval.
        """
        stats = self._store.get_stats()
        latest = self._store.get_latest_checkpoint()

        console.print()
        console.print("[bold cyan]resume-agent — Status[/bold cyan]")

        if latest:
            ts_str = latest.get("timestamp", "")
            task_type = latest.get("task_type", "?")
            summary = latest.get("summary", "")[:80]
            console.print(f"[dim]Last checkpoint:[/dim] {task_type} — {summary}…")
        else:
            console.print("[dim]No checkpoints yet.[/dim]")

        console.print(
            f"[dim]Watcher:[/dim] {'running' if self._running else 'stopped'} "
            f"(interval: {self._watcher.interval}s)"
        )
        console.print()

        if not stats:
            console.print("[dim]No interruption statistics yet. Use --interrupt a few times.[/dim]")
            return

        table = Table(
            title="Interruption Statistics",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Task Type", style="bold", min_width=16)
        table.add_column("Interruptions", justify="center")
        table.add_column("Avg Time Before Interrupt", justify="right")
        table.add_column("Recommended Interval", justify="right", style="green")

        for task_type, data in sorted(stats.items(), key=lambda x: -x[1]["count"]):
            avg_sec = data["avg_time_before_interrupt"]
            rec_sec = data["recommended_interval"]
            table.add_row(
                task_type,
                str(data["count"]),
                _format_seconds(avg_sec),
                _format_seconds(rec_sec),
            )

        console.print(table)
        console.print()

    def history(self, *, limit: int = 10) -> None:
        """
        Print a table of the most recent checkpoints, so past interruptions
        can be browsed instead of only ever seeing the latest one.
        """
        checkpoints = self._store.get_recent_checkpoints(limit=limit)

        console.print()
        console.print(f"[bold cyan]resume-agent — History (last {limit})[/bold cyan]")
        console.print()

        if not checkpoints:
            console.print("[dim]No checkpoints yet. Use --interrupt to save one.[/dim]")
            return

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("When", style="dim", min_width=19)
        table.add_column("Task Type", style="bold", min_width=16)
        table.add_column("Summary", overflow="fold")

        for cp in checkpoints:
            ts_str = cp.get("timestamp", "")
            when = ts_str
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    when = ts.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            summary = (cp.get("summary", "") or "")[:100]
            if len(cp.get("summary", "")) > 100:
                summary += "…"
            table.add_row(when, cp.get("task_type", "?"), summary)

        console.print(table)
        console.print()

    def watch(self) -> None:
        """
        Start the watcher and block (for use as a standalone background daemon).

        Can be interrupted with Ctrl+C.
        """
        self.start_watcher()
        console.print("[bold green]Watcher is running. Press Ctrl+C to stop.[/bold green]")
        console.print(
            f"[dim]Monitoring:[/dim] {self._repo_path}  "
            f"[dim]Interval:[/dim] {self._watcher.interval}s"
        )
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[dim]Watcher stopped.[/dim]")
            self.stop()

    # ── Adaptive interval ─────────────────────────────────────────────────────

    def _adapt_interval(self, task_type: str) -> None:
        """
        If the average time before interruption for `task_type` is shorter
        than the current watcher interval, tighten the interval.

        Logic: new_interval = max(min_interval, avg_time / 2)
        """
        stats = self._store.get_stats()
        if task_type not in stats:
            return

        recommended = stats[task_type]["recommended_interval"]
        current = self._watcher.interval

        if recommended < current:
            self._watcher.set_interval(recommended)
            console.print(
                f"[dim]Adaptive checkpointing: tightened interval from "
                f"{current}s → {recommended}s for '{task_type}' tasks.[/dim]"
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _take_fresh_snapshot(self) -> WorkSnapshot:
        """Take an on-demand snapshot without the watcher thread."""
        from watcher import (
            WorkSnapshot,
            get_git_diff,
            get_recent_commits,
            get_terminal_tail,
            get_active_files,
        )
        from datetime import datetime, timezone

        return WorkSnapshot(
            timestamp=datetime.now(timezone.utc),
            git_diff=get_git_diff(self._repo_path),
            recent_commits=get_recent_commits(self._repo_path),
            terminal_tail=get_terminal_tail(),
            active_files=get_active_files(self._repo_path),
            repo_path=str(self._repo_path),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _format_seconds(seconds: float) -> str:
    """Format a duration in seconds as a human-readable string."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m {s % 60}s"
    else:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"