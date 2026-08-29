# resume-agent

**Never lose your train of thought again.**

An autonomous agent that watches your development work, and when you get interrupted, reconstructs not just *what* you were doing — but *why*. Over time, it learns which kinds of tasks get interrupted most often, and adapts its own checkpoint timing automatically.

Built for the **All Things Agentic Hackathon** — Collaborative Partner track.

---

## The Problem

Every developer knows this: you're deep in a bug, then a meeting pulls you away. Twenty minutes later you're back, staring at your own diff, trying to reconstruct your train of thought. That "resume cost" adds up to hours of lost focus every week — and existing tools save your open file, not your reasoning.

## The Solution

resume-agent runs autonomously in the background, watching your git diff, terminal output, and commit history. When you're interrupted, it uses Gemini to infer *why* you were doing what you were doing — not just restate the diff. When you return, it surfaces that reconstructed context and asks one quick clarifying question to confirm its inference. Your correction feeds back into future classifications, making it a genuine collaborative partner rather than a one-shot summarizer.

It also learns your personal interruption patterns: it tracks which task types (debugging, new features, code review, refactoring) get interrupted most often, and tightens its own checkpoint interval for those task types automatically — no configuration required.

---

## Features

- **Autonomous observation** — polls git diff, recent commits, and terminal output in the background; no manual prompting required to capture context
- **Reasoning, not restating** — Gemini infers developer intent from the signals (e.g. "fixing a null check flagged in review", not "edited parser.go")
- **Collaborative clarification** — asks one confirming question on resume; corrections improve future classification accuracy
- **Adaptive checkpointing** — automatically tightens checkpoint frequency for task types that get interrupted fastest, learned entirely from behavior
- **Persistent, scalable storage** — checkpoints and pattern statistics are stored in Cloud Firestore
- **Live public dashboard** — a read-only web dashboard (deployed on Firebase Hosting) visualizes interruption statistics and recent checkpoints in real time
- **Installable CLI** — `pip install` straight from this repo; no manual script running required
- **First-run setup wizard** — `resume-agent --setup` walks through configuration interactively, no manual `.env` editing needed
- **Browsable history** — `resume-agent --history` surfaces past checkpoints, not just the latest

---

## Architecture

```
Observer  →  Checkpoint Agent  →  Firestore  →  Pattern Learner
(git diff,     (Gemini + ADK,      (persists       (tightens
 terminal,      infers WHY,         checkpoints      checkpoint
 commits)       not just WHAT)      + stats)         interval per
                                                       task type)
                     ↑                                    │
                     └──────────── feedback loop ──────────┘
              (adaptive interval feeds back into the Observer —
                        no human in the loop)
```

The agent is event-driven and autonomous — not a request/response chat loop. The only user-initiated actions are the interruption trigger and the resume trigger (simulating what a real calendar/Slack integration would fire automatically); everything else — reasoning about intent, classifying task type, adjusting checkpoint timing — happens without prompting.

---

## Tech Stack

| Component | Technology |
|---|---|
| Reasoning engine | Gemini 3.5, via the Gemini API |
| Agent framework | Google Agent Development Kit (ADK) — `LlmAgent` with tool-calling |
| Storage | Cloud Firestore |
| Public dashboard | Firebase Hosting, designed with Google Stitch |
| CLI | Python, `rich` for terminal output, installable via `pip` |

---

## Installation

```bash
pip install git+https://github.com/YOUR_USERNAME/resume-agent.git
```

Or, for local development:

```bash
git clone https://github.com/YOUR_USERNAME/resume-agent.git
cd resume-agent
pip install -e .
```

## Setup

Run the interactive setup wizard — no manual `.env` editing required:

```bash
resume-agent --setup
```

You'll be asked for:
- A Gemini API key (get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- The project path you want the agent to watch
- Your storage backend (`sqlite` for local-only, or `firestore` if you have a Google Cloud / Firebase project)

## Usage

```bash
# Capture a checkpoint of your current work context
resume-agent --interrupt

# Surface the latest checkpoint and confirm/correct its classification
resume-agent --resume

# View interruption statistics and adaptive checkpoint intervals
resume-agent --status

# Browse past checkpoints
resume-agent --history

# Point at a different project without editing config
resume-agent --interrupt --repo "/path/to/other/project"

# Run the background watcher continuously
resume-agent --watch
```

## Live Dashboard

A read-only public dashboard visualizes checkpoint history and interruption statistics in real time, backed by the same Firestore data the CLI writes to:

**[resume-agent-44270.web.app](https://resume-agent-44270.web.app)**

---

## Project Structure

```
resume-agent/
├── cli.py               # CLI entry point (argparse + rich)
├── main.py               # orchestrator — ties watcher, agent, and storage together
├── checkpoint_agent.py    # ADK agent definition + Gemini reasoning
├── clarify.py             # clarifying question flow (Collaborative Partner loop)
├── watcher.py             # background observer — git diff, terminal, commits
├── pattern_store.py       # storage layer — SQLite and Firestore backends
├── config.py              # centralized configuration loader
├── pyproject.toml         # packaging — makes the CLI pip-installable
└── dashboard/             # public web dashboard (Firebase Hosting)
```

---

## Findings & Learnings

- **Reasoning about intent, not just summarizing diffs, requires deliberate prompt design.** An early version of the system prompt produced generic restatements of the diff; explicitly instructing the model to infer *why*, quote specific identifiers, and distinguish task types produced meaningfully more useful checkpoints.
- **Cross-invocation state needs to live in storage, not memory.** Since each CLI call is a fresh process, tracking "time since last interruption" required reading the previous checkpoint's timestamp from Firestore/SQLite rather than relying on in-memory state — a good reminder that CLI tools can't assume process continuity.
- **Signal weighting matters.** When terminal output and git diff disagree (e.g. a stale error in terminal history vs. a fresh, unrelated code change), the model's classification leans on whichever signal is more specific — worth tuning further with real usage data.

## Future Work

- Real interruption detection via OS-level idle-time monitoring, replacing the manual `--interrupt` trigger
- Calendar/Slack integration for genuinely automatic interruption signals
- IDE integration (VS Code extension) for file-save-based triggering instead of polling
- Multi-repo pattern tracking for developers working across several active projects
- A downstream analytics layer (in progress) separating Firestore as the operational store from a data warehouse for longer-term trend analysis across weeks of behavior

---

## License

Built for the All Things Agentic Hackathon (Collaborative Partner track).