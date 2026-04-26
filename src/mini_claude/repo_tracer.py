"""
Repo-level execution tracer and multi-file HTML visualizer.

Unlike visualizer.py (which traces a user-supplied code snippet), this module
traces the actual mini_claude source files as they execute, filtering out
stdlib and third-party frames so only our code is shown.

Public API:
    open_repo_visualization(user_prompt) -> str
        Runs a dry-run of the agent loop with a mock Bedrock client, traces
        through cli.py / agent.py / tools.py, generates a multi-file animated
        HTML page, and opens it in VS Code Simple Browser or browser.

How it works:
    1. MockClient fakes the Anthropic SDK streaming interface so no real API
       call is made — it returns predefined responses for "list the files here".
    2. sys.settrace fires on every line/call/return in our source files.
    3. Each event is stored as a step dict with filename, lineno, locals, etc.
    4. generate_repo_html() embeds all source files + steps as JSON in one
       self-contained HTML file; JavaScript handles tab switching and animation.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

# Directory containing our source files — only frames from here are traced
_SRC_DIR = Path(__file__).parent.resolve()


# ── Mock Anthropic SDK ────────────────────────────────────────────────────────
# These classes mimic just enough of the SDK surface that agent.py's
# client.messages.stream(...) pattern works without modification.

@dataclass
class _TextBlock:
    type: str = "text"
    text: str = ""

@dataclass
class _ToolUseBlock:
    type: str = "tool_use"
    id: str = "toolu_mock_001"
    name: str = ""
    input: dict = field(default_factory=dict)

@dataclass
class _Usage:
    input_tokens: int = 200
    output_tokens: int = 50

@dataclass
class _Message:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: _Usage = field(default_factory=_Usage)


class _Stream:
    """Context manager that mimics client.messages.stream()."""

    def __init__(self, message: _Message) -> None:
        self._message = message
        self._text = "".join(b.text for b in message.content if b.type == "text")

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    @property
    def text_stream(self):
        for word in self._text.split():
            yield word + " "

    def get_final_message(self) -> _Message:
        return self._message


class _Messages:
    def __init__(self, streams: list[_Stream]) -> None:
        self._iter = iter(streams)

    def stream(self, **_kwargs: Any) -> _Stream:
        return next(self._iter)


class MockClient:
    """Drop-in replacement for AnthropicBedrock — returns scripted responses."""

    def __init__(self, responses: list[_Message]) -> None:
        self.messages = _Messages([_Stream(r) for r in responses])


# ── Tracer ────────────────────────────────────────────────────────────────────

def _is_our_file(filename: str) -> bool:
    try:
        return Path(filename).resolve().is_relative_to(_SRC_DIR)
    except (ValueError, OSError):
        return False


def _short_name(filename: str) -> str:
    """'…/src/mini_claude/agent.py' → 'agent.py'"""
    try:
        return Path(filename).resolve().relative_to(_SRC_DIR).as_posix()
    except ValueError:
        return Path(filename).name


# Variables we never want cluttering the panel
_SKIP_VARS = frozenset({"console", "client", "stream", "log", "self"})


def _safe(value: Any) -> Any:
    """Return a JSON-serializable deep copy (no truncation — display handled in HTML).

    json.loads(json.dumps(...)) gives a fresh copy so later mutations to the
    original list/dict don't corrupt already-stored steps.
    """
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return repr(value)


def trace_repo(
    user_prompt: str,
    *,
    responses: list[_Message] | None = None,
    client: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """
    Run run_agent() under sys.settrace, filtering to our source files only.

    Pass either:
      responses=  — scripted mock replies (no AWS call, instant)
      client=     — a real AnthropicBedrock client (live AWS call)

    Returns (steps, sources):
        steps   — one dict per tracer event in our source files
        sources — filename -> list of source lines (for the HTML)
    """
    from mini_claude.agent import run_agent
    from mini_claude.config import settings

    if client is None:
        client = MockClient(responses or [])

    steps: list[dict[str, Any]] = []
    sources: dict[str, list[str]] = {}

    def _tracer(frame: Any, event: str, arg: Any) -> Any:
        if not _is_our_file(frame.f_code.co_filename):
            return None  # ignore — stdlib / third-party frame

        short = _short_name(frame.f_code.co_filename)

        if short not in sources:
            try:
                sources[short] = Path(frame.f_code.co_filename).read_text(encoding="utf-8").splitlines()
            except Exception:
                sources[short] = []

        lineno = frame.f_lineno
        src_lines = sources.get(short, [])
        line_src = src_lines[lineno - 1].rstrip() if 0 < lineno <= len(src_lines) else ""

        locals_snap = {
            k: _safe(v)
            for k, v in frame.f_locals.items()
            if not k.startswith("_") and k not in _SKIP_VARS
        }

        steps.append({
            "filename": short,
            "lineno": lineno,
            "event": event,
            "function": frame.f_code.co_name,
            "locals": locals_snap,
            "line_src": line_src,
            "retval": _safe(arg) if event == "return" else None,
        })
        return _tracer  # keep tracing inside this frame

    quiet = Console(file=io.StringIO())  # discard terminal output during trace
    history: list[dict] = []

    sys.settrace(_tracer)
    try:
        run_agent(
            user_message=user_prompt,
            history=history,
            client=client,
            settings=settings,
            console=quiet,
        )
    finally:
        sys.settrace(None)

    return steps, sources


# ── HTML generator ────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_id(filename: str) -> str:
    """Turn 'agent.py' into a valid HTML id."""
    return filename.replace("/", "_").replace(".", "_").replace("-", "_")


def generate_repo_html(sources: dict[str, list[str]], steps: list[dict[str, Any]]) -> str:
    """Return a self-contained multi-file animated HTML page."""

    filenames = list(sources.keys())
    steps_json = json.dumps(steps)
    total = len(steps)

    # One hidden <div> per file; JS shows/hides them as tabs switch
    code_panels = ""
    for fname, lines in sources.items():
        fid = _safe_id(fname)
        display = "block" if fname == filenames[0] else "none"
        code_lines = "\n".join(
            f'<div class="cl" id="{_esc(fname)}:L{i + 1}">'
            f'<span class="ln">{i + 1:>4}</span>'
            f'<span class="src">{_esc(line)}</span>'
            f"</div>"
            for i, line in enumerate(lines)
        )
        code_panels += (
            f'<div class="fpanel" id="fp_{fid}" style="display:{display}">'
            f"{code_lines}</div>\n"
        )

    tabs = "".join(
        f'<button class="tab" id="tab_{_safe_id(f)}" onclick="switchFile({json.dumps(f)})">'
        f"{_esc(f)}</button>"
        for f in filenames
    )

    filenames_json = json.dumps(filenames)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Repo Execution Trace</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#1e1e1e;color:#d4d4d4;font:13px/1.5 Consolas,'Courier New',monospace;
       display:flex;flex-direction:column;height:100vh;overflow:hidden}}
  #hd{{background:#252526;border-bottom:1px solid #333;padding:6px 14px;
       display:flex;align-items:center;gap:10px;flex-shrink:0}}
  #hd h1{{font-size:13px;font-weight:600;color:#ccc}}
  .badge{{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700}}
  .b-line{{background:#0d3a58;color:#4fc1ff}}
  .b-call{{background:#1e3a1e;color:#4ec9b0}}
  .b-return{{background:#3a2d1e;color:#ce9178}}
  .b-exception{{background:#5a1d1d;color:#f48771}}
  #fn{{font-size:11px;color:#858585;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  #ctr{{font-size:11px;color:#858585;white-space:nowrap}}
  #tabs{{background:#2d2d2d;border-bottom:1px solid #333;display:flex;
         gap:2px;padding:0 8px;flex-shrink:0;overflow-x:auto}}
  .tab{{background:transparent;color:#888;border:none;border-bottom:2px solid transparent;
        padding:5px 14px;cursor:pointer;font:12px Consolas,monospace;white-space:nowrap}}
  .tab:hover{{color:#ccc;background:#333}}
  .tab.active{{color:#fff;border-bottom-color:#007acc;background:#1e1e1e}}
  #main{{display:flex;flex:1;overflow:hidden}}
  #cp{{flex:0 0 64%;border-right:1px solid #333;overflow-y:auto;padding:4px 0}}
  .cl{{display:flex;white-space:pre;padding:1px 0;transition:background .12s}}
  .cl .ln{{color:#555;min-width:44px;padding:0 8px;text-align:right;
           border-right:1px solid #2a2a2a;margin-right:10px;user-select:none;flex-shrink:0}}
  .cl.active{{background:#094771}}
  .cl.active .ln{{color:#569cd6;border-right-color:#007acc}}
  .cl.visited{{background:#1a2e1a}}
  #vp{{flex:1;overflow-y:auto;padding:12px}}
  #vp h2{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#555;margin-bottom:8px}}
  .vr{{display:flex;gap:6px;padding:2px 6px;border-radius:3px;margin-bottom:1px;
       font-size:12px;align-items:baseline;flex-wrap:wrap}}
  .vr.changed{{animation:flash .5s ease}}
  @keyframes flash{{0%{{background:#4a5f1a}}100%{{background:transparent}}}}
  .vn{{color:#9cdcfe;min-width:110px;flex-shrink:0}}
  .vt{{color:#4ec9b0;font-size:10px;min-width:50px;opacity:.7;flex-shrink:0}}
  .vv{{color:#ce9178;word-break:break-word;flex:1}}
  .vv.num{{color:#b5cea8}}
  .vv.bl{{color:#569cd6}}
  .vpre{{margin:3px 0 4px 0;padding:5px 8px;background:#1a1a1a;border-radius:3px;
         font-size:11px;color:#ce9178;white-space:pre-wrap;word-break:break-word;
         max-height:200px;overflow-y:auto;border-left:2px solid #444;width:100%}}
  details{{width:100%;cursor:pointer}}
  details>summary{{list-style:none;outline:none}}
  details>summary::-webkit-details-marker{{display:none}}
  .retbox{{margin-top:8px;padding:6px 8px;background:#2a2010;
           border-left:3px solid #ce9178;border-radius:2px;font-size:11px}}
  .empty{{color:#444;font-size:11px}}
  #ctrl{{background:#252526;border-top:1px solid #333;padding:6px 14px;
         display:flex;align-items:center;gap:8px;flex-shrink:0}}
  button.cb{{background:#0e639c;color:#fff;border:none;padding:3px 12px;
             border-radius:3px;cursor:pointer;font:12px Consolas,monospace}}
  button.cb:hover{{background:#1177bb}}
  button.cb:disabled{{background:#333;color:#555;cursor:default}}
  #pbtn{{background:#16825d;min-width:60px}}
  #pbtn:hover{{background:#1a9068}}
  #pbtn.on{{background:#7a3010}}
  #sc{{flex:1;accent-color:#007acc}}
  select{{background:#3c3c3c;color:#ccc;border:1px solid #555;border-radius:3px;
          padding:2px 4px;font:11px Consolas,monospace}}
  #hint{{font-size:10px;color:#444;margin-left:auto}}
</style>
</head>
<body>

<div id="hd">
  <h1>Repo Trace &nbsp;|</h1>
  <span id="badge" class="badge b-line">line</span>
  <span id="fn"></span>
  <span id="ctr">Step 1 / {total}</span>
</div>

<div id="tabs">{tabs}</div>

<div id="main">
  <div id="cp">{code_panels}</div>
  <div id="vp">
    <h2>Variables</h2>
    <div id="vc"></div>
  </div>
</div>

<div id="ctrl">
  <button class="cb" id="pvbtn" onclick="go(cur-1)">&#9664; Prev</button>
  <button class="cb" id="pbtn"  onclick="togglePlay()">&#9654; Play</button>
  <button class="cb" id="nxbtn" onclick="go(cur+1)">Next &#9654;</button>
  <input id="sc" type="range" min="0" max="{total - 1}" value="0" oninput="go(+this.value)">
  <select id="spd" onchange="setSpeed()">
    <option value="1400">Slow</option>
    <option value="700" selected>Normal</option>
    <option value="250">Fast</option>
    <option value="60">Very fast</option>
  </select>
  <span id="hint">&#8592; &#8594; step &nbsp;|&nbsp; Space play</span>
</div>

<script>
const steps={steps_json};
const N=steps.length;
const fileNames={filenames_json};
let cur=0,playing=false,timer=null,speed=700,activeFile=null;

function sid(f){{return f.replace(/[^a-zA-Z0-9]/g,'_');}}
function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function tn(v){{
  if(v===null||v==='None')return'None';
  if(typeof v==='boolean')return'bool';
  if(typeof v==='number')return Number.isInteger(v)?'int':'float';
  if(typeof v==='string')return'str';
  if(Array.isArray(v))return`list[${{v.length}}]`;
  return typeof v==='object'?`dict[${{Object.keys(v).length}}]`:typeof v;
}}
function vc(v){{return typeof v==='number'?' num':typeof v==='boolean'?' bl':'';}}
function dv(v){{
  if(v===null||v==='None')return'<span class="vv">None</span>';
  if(typeof v==='boolean')return`<span class="vv bl">${{v}}</span>`;
  if(typeof v==='number')return`<span class="vv num">${{v}}</span>`;
  if(typeof v==='string')return`<span class="vv">${{esc(v)}}</span>`;
  const compact=JSON.stringify(v);
  if(compact.length<=120)return`<span class="vv">${{esc(compact)}}</span>`;
  const pretty=esc(JSON.stringify(v,null,2));
  const summ=esc(compact.slice(0,80))+(compact.length>80?'&hellip;':'');
  return`<details><summary><span class="vv">${{summ}}</span></summary><pre class="vpre">${{pretty}}</pre></details>`;
}}

function switchFile(f){{
  if(activeFile===f)return;
  if(activeFile){{
    const op=document.getElementById('fp_'+sid(activeFile));if(op)op.style.display='none';
    const ot=document.getElementById('tab_'+sid(activeFile));if(ot)ot.classList.remove('active');
  }}
  activeFile=f;
  const p=document.getElementById('fp_'+sid(f));if(p)p.style.display='block';
  const t=document.getElementById('tab_'+sid(f));if(t)t.classList.add('active');
}}

function renderVars(s,prev){{
  const pl=prev?prev.locals:{{}};
  const vc2=document.getElementById('vc');
  document.getElementById('badge').textContent=s.event;
  document.getElementById('badge').className='badge b-'+s.event;
  const fn=s.function==='<module>'?s.filename:'in '+s.function+'()';
  document.getElementById('fn').textContent=fn+' — '+s.filename+':'+s.lineno;
  const loc=s.locals||{{}};
  const keys=Object.keys(loc);
  if(!keys.length&&!s.retval){{vc2.innerHTML='<div class="empty">No local variables</div>';return;}}
  let h='';
  for(const[k,v]of Object.entries(loc)){{
    const ch=JSON.stringify(v)!==JSON.stringify(pl[k]);
    h+=`<div class="vr${{ch?' changed':''}}"><span class="vn">${{esc(k)}}</span><span class="vt">${{esc(tn(v))}}</span>${{dv(v)}}</div>`;
  }}
  if(s.retval!==null&&s.retval!==undefined)
    h+=`<div class="retbox">&#8617; return: ${{dv(s.retval)}}</div>`;
  vc2.innerHTML=h;
}}

function go(n){{
  if(n<0||n>=N)return;
  const old=steps[cur];
  if(old.lineno>0){{const el=document.getElementById(old.filename+':L'+old.lineno);if(el){{el.classList.remove('active');el.classList.add('visited');}}}}
  cur=n;
  const s=steps[cur];
  switchFile(s.filename);
  if(s.lineno>0){{const el=document.getElementById(s.filename+':L'+s.lineno);if(el){{el.classList.remove('visited');el.classList.add('active');el.scrollIntoView({{block:'nearest',behavior:'smooth'}});}}}}
  renderVars(s,n>0?steps[n-1]:null);
  document.getElementById('ctr').textContent='Step '+(n+1)+' / '+N;
  document.getElementById('sc').value=n;
  document.getElementById('pvbtn').disabled=n===0;
  document.getElementById('nxbtn').disabled=n===N-1;
  if(n===N-1&&playing)stopPlay();
}}
function togglePlay(){{playing?stopPlay():startPlay();}}
function startPlay(){{
  playing=true;const b=document.getElementById('pbtn');b.textContent='&#9646;&#9646; Pause';b.classList.add('on');
  timer=setInterval(()=>{{if(cur<N-1)go(cur+1);else stopPlay();}},speed);
}}
function stopPlay(){{
  playing=false;clearInterval(timer);const b=document.getElementById('pbtn');b.textContent='&#9654; Play';b.classList.remove('on');
}}
function setSpeed(){{speed=+document.getElementById('spd').value;if(playing){{stopPlay();startPlay();}}}}
document.addEventListener('keydown',e=>{{
  if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
  if(e.key==='ArrowRight')go(cur+1);if(e.key==='ArrowLeft')go(cur-1);
  if(e.key===' '){{e.preventDefault();togglePlay();}}
}});
// init first tab
const ft=document.getElementById('tab_'+sid(fileNames[0]));if(ft)ft.classList.add('active');
activeFile=fileNames[0];
go(0);
</script>
</body>
</html>"""


# ── Public entry point ────────────────────────────────────────────────────────

def open_repo_visualization(
    user_prompt: str = "list the files here",
    *,
    client: Any = None,
) -> str:
    """
    Trace our source files and open an animated multi-file HTML page.

    client=None  — uses a mock client (no AWS call, instant, default)
    client=<real AnthropicBedrock>  — makes a live call; trace shows real
                                      tool choices and replies from Claude
    Returns path to the generated HTML file.
    """
    if client is not None:
        # Live path: trace a real AWS call
        steps, sources = trace_repo(user_prompt, client=client)
    else:
        # Mock path: scripted two-round-trip "list files" flow
        from mini_claude.tools import list_files

        file_listing = list_files(".")
        final_reply = (
            f"Here are the files in the current directory:\n\n{file_listing}"
            "\n\nLet me know if you'd like details on any of these."
        )
        responses = [
            _Message(
                stop_reason="tool_use",
                usage=_Usage(input_tokens=300, output_tokens=40),
                content=[_ToolUseBlock(id="toolu_mock_001", name="list_files", input={"path": "."})],
            ),
            _Message(
                stop_reason="end_turn",
                usage=_Usage(input_tokens=500, output_tokens=80),
                content=[_TextBlock(text=final_reply)],
            ),
        ]
        steps, sources = trace_repo(user_prompt, responses=responses)
    html = generate_repo_html(sources, steps)

    fd, path = tempfile.mkstemp(suffix=".html", prefix="mini_claude_repo_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)

    file_url = "file:///" + path.replace("\\", "/")
    vscode_url = "vscode://vscode.simpleBrowser.show?url=" + urllib.parse.quote(file_url, safe="")
    try:
        result = subprocess.run(["code", "--open-url", vscode_url], capture_output=True, timeout=5)
        if result.returncode == 0:
            return path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    webbrowser.open(file_url)
    return path
