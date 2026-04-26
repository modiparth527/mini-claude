# Mini Claude Code

<!-- After pushing to GitHub: edit README.md in the browser, drag your MP4 into
     the editor, and GitHub will replace this comment with a hosted video URL. -->

A minimal coding agent built with the Anthropic SDK on AWS Bedrock — a learning project to understand how Claude Code works under the hood.

## What it does

Runs an interactive terminal session where you type messages and Claude can respond with text **and** call tools (read files, write files, run shell commands, list directories) to actually do things on your machine.

Type `/trace` to open an animated step-by-step visualization of the agent's own execution through the codebase.

## Project structure

```
src/mini_claude/
├── config.py        — AWS Bedrock settings loaded from .env / env vars
├── tools.py         — tool schemas (what Claude sees) + Python implementations
├── agent.py         — the agentic loop: send → stream → handle tool calls → repeat
├── cli.py           — interactive REPL, slash commands, wires everything together
├── visualizer.py    — single-file execution tracer + animated HTML generator
└── repo_tracer.py   — whole-repo tracer: runs agent under sys.settrace, multi-file HTML

tests/
└── test_tools.py    — unit tests for all tools (no AWS credentials needed)

examples/
├── debug_flow.py    — interactive ASCII walkthrough of the "list files" agent flow
├── test_viz.py      — standalone smoke test for the single-file visualizer
├── test_repo_viz.py — standalone smoke test for the repo visualizer
└── list_models.py   — lists all available Anthropic models on your Bedrock account
```

## Setup

**1. Log in via AWS SSO** (redo when your token expires)

```powershell
aws sso login --profile <your-profile-name>
```

**2. Create `.env`** (choose one backend)

```ini
# ── Option A: direct Anthropic API ───────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
MODEL=claude-sonnet-4-6          # or claude-opus-4-7 / claude-haiku-4-5-20251001

# ── Option B: AWS Bedrock via SSO ────────────────────────────────────────────
# (no API key needed — uses your AWS credentials)
AWS_REGION=us-east-1
AWS_PROFILE=your-sso-profile     # SSO profile from ~/.aws/config
BEDROCK_MODEL=us.anthropic.claude-sonnet-4-6

# ── Mode (optional — default is "auto") ──────────────────────────────────────
# auto      → Anthropic API if ANTHROPIC_API_KEY is set, else Bedrock
# anthropic → always use Anthropic API
# bedrock   → always use Bedrock
# MODE=auto
```

**3. Install dependencies** (requires Python 3.11+)

```bash
pip install -e .
```

**4. Run**

```bash
mini-claude                        # auto-detect backend from .env
mini-claude --mode anthropic       # force Anthropic API
mini-claude --mode bedrock         # force AWS Bedrock
mini-claude --verbose              # show debug logs (token counts, tool details)
```

## Slash commands

| Command | What it does |
|---|---|
| `/trace` | Trace a mock dry-run of the agent through the repo, open animated HTML (no AWS call) |
| `/trace <prompt>` | Same but with a real AWS Bedrock call using your prompt |
| `/history` | Print the full conversation history as JSON |
| `/clear` | Clear conversation history |
| `/exit` | Quit |

## How the agent loop works

```
you type a message
        ↓
  append to history
        ↓
  call Claude (Bedrock)  ←──────────────────────────────┐
        ↓                                                │
  stream text tokens to terminal                         │
        ↓                                                │
  did Claude call any tools?                             │
     NO → break, wait for next input                     │
     YES ↓                                               │
  execute each tool (read_file, run_bash, list_files…)   │
        ↓                                                │
  append tool results to history ───────────────────────┘
```

## Development

```bash
# Run tests
pytest

# Lint
ruff check src/ tests/

# Auto-fix
ruff check src/ tests/ --fix

# Format
ruff format src/ tests/
```

## How to add a new tool

1. Add a schema entry to `TOOLS` in [tools.py](src/mini_claude/tools.py)
2. Write the Python function below it
3. Register it in `_REGISTRY` at the bottom of the file
4. Add a test in [tests/test_tools.py](tests/test_tools.py)

## Learning exercises

- Add a `search_files` tool using `glob` or `os.walk`
- Print token usage after each response (`message.usage`)
- Add `/save` and `/load` commands to persist conversation history
- Swap models in `.env`: `us.anthropic.claude-opus-4-7` vs `us.anthropic.claude-haiku-4-5-20251001`
- Extend the repo tracer to also highlight the call stack depth
