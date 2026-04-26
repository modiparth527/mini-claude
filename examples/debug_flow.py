"""
Annotated dry-run of the entire mini-claude agent loop.
Simulates: user types "list the files here"

No API key or AWS credentials needed -- uses mock Claude responses.
Run: .venv\\Scripts\\python debug_flow.py
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Formatting helpers ────────────────────────────────────────────────────────

def section(title: str) -> None:
    print(f"\n{'=' * 68}")
    print(f"  {title}")
    print(f"{'=' * 68}")

def step(n: int, file: str, line: int, desc: str) -> None:
    print(f"\n  +-- STEP {n}  {file}:{line}")
    for part in desc.splitlines():
        print(f"  |  {part}")
    print(f"  +{'-' * 60}")

def show(label: str, value: Any) -> None:
    text = json.dumps(value, indent=2) if isinstance(value, (dict, list)) else repr(value)
    print(f"\n    [{label}]")
    for ln in text.splitlines():
        print(f"      {ln}")

def pause() -> None:
    input("\n  >> press Enter to continue...")

# ── Mock SDK types ────────────────────────────────────────────────────────────

@dataclass
class TextBlock:
    type: str = "text"
    text: str = ""

@dataclass
class ToolUseBlock:
    type: str = "tool_use"
    id: str = "toolu_01AbCdEfGhIjKl"
    name: str = "list_files"
    input: dict = field(default_factory=lambda: {"path": "."})

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

@dataclass
class MockMessage:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)

# ── Simulated tool execution ──────────────────────────────────────────────────

def list_files(path: str = ".") -> str:
    try:
        entries = sorted(Path(path).iterdir(), key=lambda e: (e.is_file(), e.name))
        lines = [f"{'[file]' if e.is_file() else '[dir] '} {e.name}" for e in entries]
        return "\n".join(lines) if lines else "(empty)"
    except Exception as exc:
        return f"Error: {exc}"

# =============================================================================
#  START
# =============================================================================

print("""
+==================================================================+
|        mini-claude  --  full agent flow debugger                 |
|        prompt: "list the files here"                             |
+==================================================================+
""")

# =============================================================================
section("PHASE 1 -- cli.py  (the REPL reads user input)")
# =============================================================================

step(1, "cli.py", 62, 'console.input() returns what the user typed')
user_input = "list the files here"
show("user_input", user_input)
pause()

step(2, "cli.py", 70, "match checks for /commands -- none match -> case _: reached")
print("""
    match user_input:
      case "/exit"    -> no
      case "/clear"   -> no
      case "/history" -> no
      case _          -> YES  ->  call run_agent()
""")
pause()

step(3, "cli.py", 84, "run_agent() called -- history is empty on the first turn")
history: list[dict] = []
show("history passed in", history)
pause()

# =============================================================================
section("PHASE 2 -- agent.py  run_agent()  (first entry)")
# =============================================================================

step(4, "agent.py", 43, "user message appended to history")
history.append({"role": "user", "content": user_input})
show("history", history)
pause()

step(5, "agent.py", 49,
     "API call #1 to Bedrock\n"
     "We send: history + TOOLS list (so Claude knows what it can call)\n"
     "Claude reads every tool's 'description' field and decides what to do")
print("""
    TOOLS sent to Claude:
      * list_files     -- "List files and directories at a path"
      * read_file      -- "Read the full text content of a file"
      * write_file     -- "Write (or overwrite) a file with the given content"
      * run_bash       -- "Execute a shell command and return stdout + stderr"
      * trace_execution -- "Execute Python code step-by-step..."

    Claude reasons:
      user said "list the files"
      -> list_files description matches perfectly
      -> I will call list_files(path=".")
""")
pause()

step(6, "agent.py", 56,
     "stream.text_stream -- Claude streams ZERO text tokens\n"
     "(Claude is calling a tool instead of replying with text)")
print('\n    (no text output -- stop_reason will be "tool_use")')
pause()

step(7, "agent.py", 60, "get_final_message() -- full response object arrives")
round1 = MockMessage(
    stop_reason="tool_use",
    usage=Usage(input_tokens=312, output_tokens=44),
    content=[
        ToolUseBlock(
            id="toolu_01AbCdEfGhIjKl",
            name="list_files",
            input={"path": "."},
        )
    ],
)
show("message.stop_reason", round1.stop_reason)
show("message.usage", {"input_tokens": 312, "output_tokens": 44})
show("message.content", [
    {"type": "tool_use", "id": "toolu_01AbCdEfGhIjKl",
     "name": "list_files", "input": {"path": "."}}
])
pause()

# =============================================================================
section("PHASE 3 -- agent.py  parsing Claude's response")
# =============================================================================

step(8, "agent.py", 78, "loop through message.content blocks")
print("""
    for block in message.content:
      block.type == "tool_use"  -> YES
        assistant_content  <- append tool_use dict
        tool_calls         <- append block (queued for execution)
""")
assistant_content: list[dict] = [
    {"type": "tool_use", "id": "toolu_01AbCdEfGhIjKl",
     "name": "list_files", "input": {"path": "."}}
]
tool_calls = [round1.content[0]]
show("assistant_content", assistant_content)
show("tool_calls (queued for execution)", [{"name": "list_files", "input": {"path": "."}}])
pause()

step(9, "agent.py", 92,
     "assistant turn saved to history\n"
     "IMPORTANT: history must contain the tool_use block\n"
     "so Claude can match it with the tool_result we send back next")
history.append({"role": "assistant", "content": assistant_content})
show("history (3 entries now)", history)
pause()

step(10, "agent.py", 95, "if not tool_calls: break  ->  NOT empty -> keep looping")
print(f"\n    len(tool_calls) = {len(tool_calls)}  ->  do NOT break, execute tools first")
pause()

# =============================================================================
section("PHASE 4 -- tools.py  executing the tool")
# =============================================================================

call = tool_calls[0]
step(11, "agent.py", 100,
     f"for call in tool_calls:\n"
     f"  call.name  = {call.name!r}\n"
     f"  call.input = {call.input}\n"
     f"  call.id    = {call.id!r}   <- must reference this ID in the result")
pause()

step(12, "tools.py", 130,
     "execute_tool('list_files', {'path': '.'})\n"
     "  _REGISTRY['list_files']  ->  list_files function\n"
     "  list_files(**{'path': '.'})  ->  runs the actual Python function")
tool_result = list_files(".")
show("tool result  (real output from list_files on THIS project)", tool_result)
pause()

step(13, "agent.py", 111,
     "tool result wrapped and appended to history as a 'user' message\n"
     "Anthropic API requires tool results to have role='user'\n"
     "tool_use_id links this result back to the tool_use block in step 9")
tool_results = [{"type": "tool_result", "tool_use_id": call.id, "content": tool_result}]
history.append({"role": "user", "content": tool_results})
show("history (4 entries -- ready for round 2)", history)
pause()

print("\n  -> while True loops back to top of agent.py")

# =============================================================================
section("PHASE 5 -- agent.py  API call #2  (Claude reads the result)")
# =============================================================================

step(14, "agent.py", 49,
     "API call #2 to Bedrock\n"
     "history now has 4 messages:\n"
     "  [0] user      : 'list the files here'\n"
     "  [1] assistant : tool_use block (list_files)\n"
     "  [2] user      : tool_result (the file listing)\n"
     "Claude now has everything it needs to write a final reply")
pause()

step(15, "agent.py", 56,
     "stream.text_stream -- Claude streams a real text reply this time")
final_text = (
    "Here are the files in the current directory:\n\n"
    + tool_result
    + "\n\nLet me know if you'd like details on any of these."
)
print("\n    Tokens arriving one by one:")
for word in final_text.replace("\n", " ").split()[:10]:
    print(f"      -> {word!r}")
print("      -> ...")
pause()

step(16, "agent.py", 60, 'get_final_message() -- stop_reason is "end_turn" this time')
show("message.stop_reason", "end_turn")
show("message.content", [{"type": "text", "text": final_text[:80] + "..."}])
pause()

step(17, "agent.py", 78, "loop through content blocks -- only text this time")
print("""
    for block in message.content:
      block.type == "text"  -> YES
        assistant_content <- append text dict
        tool_calls        <- nothing added  (stays empty)
""")
tool_calls = []
show("tool_calls", tool_calls)
pause()

step(18, "agent.py", 95, "if not tool_calls: break  ->  EMPTY -> BREAK")
print("\n    len(tool_calls) = 0  ->  break out of while True  ->  done!")
pause()

# =============================================================================
section("PHASE 6 -- cli.py  back in the REPL")
# =============================================================================

history.append({"role": "assistant", "content": [{"type": "text", "text": final_text}]})

step(19, "cli.py", 84, "run_agent() returned updated history -- 5 entries total")
show("final history", [
    {"role": "user",      "content": "list the files here"},
    {"role": "assistant", "content": "[tool_use: list_files(path='.')]"},
    {"role": "user",      "content": "[tool_result: <file listing>]"},
    {"role": "assistant", "content": "[text: Here are the files...]"},
])
pause()

step(20, "cli.py", 62,
     "while True loops back -- console.input() waits for the next message\n"
     "history is kept -> Claude remembers this conversation on the next turn")

# =============================================================================
section("COMPLETE FLOW SUMMARY")
# =============================================================================

print("""
  cli.py              agent.py                     tools.py / Bedrock
  ------              --------                     ------------------

  user types
  "list files"
      |
      v
  run_agent() ------> append to history
                           |
                           v
                      +-- while True -------------------------------------+
                      |                                                   |
                      |  API call #1 ----------------------------------> Bedrock
                      |                          Claude reads TOOLS       |
                      |                          picks list_files  <------+
                      |         stop_reason = "tool_use"
                      |                      |
                      |                      v
                      |             save assistant turn
                      |             to history
                      |                      |
                      |                      v
                      |             execute_tool() -----------------> tools.py
                      |                              result  <--------------+
                      |                      |
                      |                      v
                      |             append tool_result
                      |             to history
                      |                      |
                      |  API call #2 ----------------------------------> Bedrock
                      |                          Claude reads result       |
                      |                          writes final reply <------+
                      |         stop_reason = "end_turn"
                      |                      |
                      +-- break <------------+
                           |
      <--------------------+
  wait for next input
  (history preserved)
""")
