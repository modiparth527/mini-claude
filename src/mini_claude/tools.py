"""
Tool definitions (JSON schemas Claude reads) and implementations (Python functions).

Keeping schemas and implementations together makes it easy to keep them in sync.
When you add a new tool, add both the schema entry in TOOLS and a function below,
then register it in execute_tool().
"""

import subprocess
from pathlib import Path
from typing import Any

from mini_claude.visualizer import open_visualization

# ---------------------------------------------------------------------------
# Schemas — sent to Claude on every API call
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read the full text content of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write (or overwrite) a file with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to write"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_bash",
        "description": "Execute a shell command and return stdout + stderr. Timeout: 30 s.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories at a path (defaults to current dir).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to list"},
            },
            "required": [],
        },
    },
    {
        "name": "trace_execution",
        "description": (
            "Execute Python code step-by-step using sys.settrace, capture every variable "
            "state at every line, and open an animated visual debugger in VS Code (or the "
            "system browser). Use this whenever the user asks to debug, trace, visualize, "
            "or step through code execution. The 'setup' parameter lets you inject example "
            "input variables before the main code runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python source code to trace, as a string.",
                },
                "setup": {
                    "type": "string",
                    "description": (
                        "Optional Python code to run before tracing begins — use this to "
                        "define example input variables (e.g. 'n = 5'). These lines will "
                        "not appear in the visualization."
                    ),
                },
            },
            "required": ["code"],
        },
    },
]

# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

_TIMEOUT_SECS = 30


def read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error reading {path}: {exc}"


def write_file(path: str, content: str) -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {path}"
    except Exception as exc:
        return f"Error writing {path}: {exc}"


def run_bash(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECS,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {_TIMEOUT_SECS} seconds"
    except Exception as exc:
        return f"Error running command: {exc}"


def list_files(path: str = ".") -> str:
    try:
        entries = sorted(Path(path).iterdir(), key=lambda e: (e.is_file(), e.name))
        lines = [f"{'[dir] ' if e.is_dir() else '[file]'} {e.name}" for e in entries]
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as exc:
        return f"Error listing {path}: {exc}"


def trace_execution(code: str, setup: str = "") -> str:
    try:
        path = open_visualization(code, setup)
        return f"Visualization opened: {path}"
    except Exception as exc:
        return f"Error generating trace: {exc}"


# ---------------------------------------------------------------------------
# Dispatcher — single entry point used by the agent loop
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Any] = {
    "read_file": read_file,
    "write_file": write_file,
    "run_bash": run_bash,
    "list_files": list_files,
    "trace_execution": trace_execution,
}


def execute_tool(name: str, inputs: dict[str, Any]) -> str:
    fn = _REGISTRY.get(name)
    if fn is None:
        return f"Unknown tool: {name!r}"
    return fn(**inputs)
