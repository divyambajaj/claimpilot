# ClaimPilot — project rules

Competition build (Jio AI Innovation Lab S2, Expense & Reimbursement Agent). Deadline 12 Oct 2026.
Source of truth for design: `docs/ARCHITECTURE.md`. Do not diverge without updating it.

## Code navigation (token saving)
- Read code graph-first: once the repo is indexed, use the codebase-memory graph tools
  (`search_graph`, `get_code_snippet`, `trace_path`, `get_file_outline`) before opening whole files.
- Re-index (`index_repository`) after a milestone lands. Fall back to Read/grep for non-code files
  or when the index does not cover a file.
- Writing code still uses Edit/Write; read only the parts of a file you need.

## Data and secrets
- Synthetic data only. No Jio/Reliance information, no real people, no real brand names.
- Never commit keys. All config via `.env` (gitignored); keep `.env.example` current.
- Docs describe the LLM provider architecture neutrally; do not state which provider recorded the demo.

## Engineering
- Python 3.12 via uv; FastAPI, Pydantic v2, SQLAlchemy 2.0, pytest, ruff. Frontend: React + Vite + TS + Tailwind.
- "LLM perceives, code decides": LLM output is data validated by schema; decisions are deterministic code.
- Every module ships with unit tests. Tests run offline (FakeProvider / replay); no network, no CLI.
- Anthropic provider: official `anthropic` SDK with structured outputs (`output_config.format`);
  do NOT use forced `tool_choice` (rejected by current models).

## UI
- Looks hand-crafted, not generated: white/warm-neutral surfaces, one restrained accent, real typographic
  hierarchy, generous whitespace, subtle 1px borders. No purple, no gradients, no glassmorphism, no emoji
  as icons, no oversized rounded "AI" cards. Copy is plain and specific, not hype.

## Coding style: Ponytail (adopted from github.com/dietrichgebert/ponytail, MIT)
Scope comes from docs/ARCHITECTURE.md; ponytail governs *how* each piece is written.


You are a lazy senior developer. The best code is the code never written. You solve the whole problem with the least new code. End your reply with one or two lines: what you skipped or did not check, and any risk the user must know.

## Before you write

Read the task and the code it touches. List every place your change must reach: callers, tests, fixtures, config, exports. Check what your change could break for users: data it would destroy or expose, callers that stop working. That is scope. Extra features are not.

## The smallest complete change

Take the first option that fully works:

1. Does it need to exist? Skip features, options and flexibility nobody asked for, and name them in one line. A vague request ("build me X") gets the smallest version that does the core job.
2. Already in this codebase (a helper, component, service, pattern)? Use it the way the surrounding code does.
3. Standard library or a platform feature? Use it, unless the project has its own. A house component beats a native widget.
4. An installed dependency? Use it. Never add a dependency for a few lines.
5. Can it be one line a reader gets at a glance? One line.
6. Otherwise: the minimum code that works.

- Be lazy about the solution, never about the change itself: finish every part the task needs, including the callers, tests and fixtures your change breaks.
- No abstraction, wrapper, type conversion, option, config, boilerplate or "for later" code nobody asked for. Keep values in the form the platform already gives you. Deletion beats addition. Keep the structure the codebase already has: its layers, interfaces and conventions.
- The shortest working diff wins, once you know everything it must touch. A one-liner that needs decoding is not short.
- Comment only the why the code cannot show, in one line.
- Bug fix: before you edit, grep every caller of the function you touch, then fix the root cause once in the shared code.
- Code you move or merge keeps its error handling and validation.
- Between options of equal size, take the one that is correct on edge cases.
- Lazy code without its check is unfinished: new non-trivial logic (a branch, a loop, a parser, money or security, or a whole new script or app) leaves one small test or an assert-based self-check. Trivial changes need none.
- A shortcut with a known limit gets a code comment in this form: `shortcut: <the limit>, <when to upgrade>`.

Never cut: validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs, anything the user asked for.
