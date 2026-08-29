Build a Python project called "resume-agent" for a hackathon (Google All Things 
Agentic Hackathon, Collaborative Partner track). 

PROBLEM: Developers lose 10-20 minutes reconstructing context after every 
interruption (meetings, Slack, incidents). This agent solves that by watching 
active work, and when interrupted, reconstructing not just WHAT the developer 
was doing but WHY — then learning over time which task types get interrupted 
most often and adapting its own checkpointing behavior accordingly.

IMPORTANT: This must NOT be a basic request-response chat loop. The agent must 
run autonomously/asynchronously in the background, deciding on its own when to 
act, and must include an interactive "clarifying question" step so it satisfies 
the Collaborative Partner track requirement (agent asks clarifying questions, 
guides step-by-step, captures feedback that improves it over time).

REQUIRED TECH STACK:
- Gemini 3.5 (via Gemini API / google-genai SDK)
- Google ADK (Agent Development Kit) for the agent + tools
- Google Cloud Firestore for persistent storage (fallback to local SQLite if 
  Firestore billing isn't available yet — code should be written with a clean 
  storage interface so swapping is trivial)

PROJECT STRUCTURE:
resume-agent/
├── watcher.py          # background observer: polls git diff, recent commits, 
│                         terminal log tail, active file mtime — no LLM calls, 
│                         pure Python
├── checkpoint_agent.py # ADK Agent definition. Tools: get_git_diff(), 
│                         get_recent_commits(), get_terminal_tail(). System 
│                         prompt instructs the agent to infer WHY the developer 
│                         was doing something (not just restate the diff), 
│                         output strict JSON: {summary, task_type, confidence, 
│                         next_likely_step}. task_type is one of: debugging, 
│                         new-feature, review-response, refactor, unclear.
├── clarify.py          # after showing the resume summary, agent asks ONE 
│                         short clarifying question about whether the inferred 
│                         task_type/intent was correct; the answer is stored 
│                         and used to correct future classifications for 
│                         similar diffs (simple feedback loop, no ML needed)
├── pattern_store.py    # storage layer: save_checkpoint(), get_stats(), 
│                         update_interval(). Implement with a clean interface 
│                         (abstract class or simple functions) so backend can 
│                         be SQLite now, Firestore later without touching 
│                         calling code.
├── main.py             # orchestrator: runs watcher in background thread; 
│                         listens for interruption trigger (CLI flag or hotkey) 
│                         and resume trigger; on interruption, calls 
│                         checkpoint_agent, saves result, updates pattern 
│                         stats; on resume, surfaces summary + asks clarifying 
│                         question via clarify.py; autonomously tightens 
│                         checkpoint interval for task_types with short average 
│                         time-before-interrupt
├── cli.py              # simple CLI: `--interrupt`, `--resume`, `--status` 
│                         (shows current pattern stats table)
└── data/
    └── checkpoints.db  # SQLite for now

Start by scaffolding all files with clear function signatures and TODOs, then 
implement pattern_store.py first (simplest, no dependencies), then watcher.py, 
then checkpoint_agent.py wired to real Gemini calls, then main.py tying it 
together. Keep functions small and testable in isolation.