"""
Execution tracer and animated HTML visualizer.

Public API:
    open_visualization(source, setup="") -> str
        Traces source under sys.settrace, generates a self-contained HTML
        animation, and opens it in VS Code Simple Browser (or falls back to
        the system browser). Returns the path to the HTML file.

How sys.settrace works (the core concept):
    Python calls a tracer function before every line, every function call,
    and every function return. We use that hook to snapshot all local
    variables at each moment, then replay those snapshots as an animation.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from typing import Any

# ── Tracer ────────────────────────────────────────────────────────────────────

_TRACED = "<traced>"  # filename we give to compile() so we can filter frames


def _safe_json(value: Any) -> Any:
    """Return a JSON-serialisable form of value, falling back to repr()."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def trace_code(source: str, setup: str = "") -> list[dict[str, Any]]:
    """
    Execute *source* under sys.settrace and return one step-dict per event.

    Each dict has:
        lineno   – 1-based line number in source  (0 = unknown)
        event    – "call" | "line" | "return" | "exception"
        function – name of the active function ("<module>" at top level)
        locals   – snapshot of local variables (JSON-safe)
        line_src – the stripped source text of that line
        retval   – return value when event == "return", else None
        error    – error message when event == "exception", else None
    """
    source_lines = source.splitlines()
    steps: list[dict[str, Any]] = []

    def _tracer(frame, event, arg):
        # Ignore frames that belong to stdlib / our own tracer machinery
        if frame.f_code.co_filename != _TRACED:
            return None

        lineno = frame.f_lineno
        line_src = source_lines[lineno - 1].rstrip() if 0 < lineno <= len(source_lines) else ""

        locals_snap = {
            k: _safe_json(v)
            for k, v in frame.f_locals.items()
            if not k.startswith("__")
        }

        steps.append(
            {
                "lineno": lineno,
                "event": event,
                "function": frame.f_code.co_name,
                "locals": locals_snap,
                "line_src": line_src,
                "retval": _safe_json(arg) if event == "return" else None,
                "error": str(arg) if event == "exception" else None,
            }
        )
        return _tracer  # returning self keeps tracing inside this frame

    # Run optional setup silently (no tracing) — used to inject example inputs
    namespace: dict[str, Any] = {}
    if setup.strip():
        exec(compile(setup, "<setup>", "exec"), namespace)  # noqa: S102

    compiled = compile(source, _TRACED, "exec")
    sys.settrace(_tracer)
    try:
        exec(compiled, namespace)  # noqa: S102
    except Exception as exc:
        steps.append(
            {
                "lineno": 0,
                "event": "exception",
                "function": "<module>",
                "locals": {},
                "line_src": "",
                "retval": None,
                "error": str(exc),
            }
        )
    finally:
        sys.settrace(None)

    return steps


# ── HTML generator ────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Minimal HTML escaping so user code can't break the page."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_html(source: str, steps: list[dict[str, Any]]) -> str:
    """Return a fully self-contained HTML page that animates the trace."""

    source_lines = source.splitlines()
    steps_json = json.dumps(steps)
    total = len(steps)

    # One <div> per source line — JavaScript highlights them by id="L{n}"
    code_html = "\n".join(
        f'<div class="cl" id="L{i + 1}">'
        f'<span class="ln">{i + 1:>3}</span>'
        f'<span class="src">{_esc(line)}</span>'
        f"</div>"
        for i, line in enumerate(source_lines)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Execution Trace</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#1e1e1e;color:#d4d4d4;font:14px/1.5 Consolas,'Courier New',monospace;
       display:flex;flex-direction:column;height:100vh;overflow:hidden}}

  /* ── header ── */
  #hd{{background:#252526;border-bottom:1px solid #333;padding:8px 14px;
       display:flex;align-items:center;gap:12px;flex-shrink:0}}
  #hd h1{{font-size:13px;font-weight:600;color:#ccc}}
  .badge{{padding:2px 9px;border-radius:10px;font-size:11px;font-weight:700}}
  .b-line{{background:#0d3a58;color:#4fc1ff}}
  .b-call{{background:#1e3a1e;color:#4ec9b0}}
  .b-return{{background:#3a2d1e;color:#ce9178}}
  .b-exception{{background:#5a1d1d;color:#f48771}}
  #fn{{font-size:12px;color:#858585}}
  #ctr{{margin-left:auto;font-size:12px;color:#858585;white-space:nowrap}}

  /* ── panels ── */
  #main{{display:flex;flex:1;overflow:hidden}}

  /* code panel */
  #cp{{flex:0 0 62%;border-right:1px solid #333;overflow-y:auto;padding:6px 0}}
  .cl{{display:flex;white-space:pre;padding:1px 0;transition:background .15s}}
  .cl .ln{{color:#5a5a5a;min-width:38px;padding:0 8px;text-align:right;
           border-right:1px solid #2a2a2a;margin-right:10px;user-select:none}}
  .cl.active{{background:#094771}}
  .cl.active .ln{{color:#569cd6;border-right-color:#007acc}}
  .cl.visited{{background:#1a2e1a}}

  /* variables panel */
  #vp{{flex:1;overflow-y:auto;padding:14px}}
  #vp h2{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;
          color:#666;margin-bottom:10px}}
  .vr{{display:flex;gap:8px;padding:3px 8px;border-radius:3px;margin-bottom:2px;
       font-size:13px;align-items:baseline}}
  .vr.changed{{animation:flash .5s ease}}
  @keyframes flash{{0%{{background:#4a5f1a}}100%{{background:transparent}}}}
  .vn{{color:#9cdcfe;min-width:90px;flex-shrink:0}}
  .vt{{color:#4ec9b0;font-size:10px;min-width:52px;opacity:.7;flex-shrink:0}}
  .vv{{color:#ce9178;word-break:break-all}}
  .vv.num{{color:#b5cea8}}
  .vv.bl{{color:#569cd6}}
  .retbox{{margin-top:10px;padding:7px 10px;background:#2a2010;
           border-left:3px solid #ce9178;border-radius:2px;font-size:12px}}
  .errbox{{margin-top:10px;padding:7px 10px;background:#2d1010;
           border-left:3px solid #f48771;border-radius:2px;font-size:12px;color:#f48771}}
  .empty{{color:#444;font-size:12px}}

  /* ── controls ── */
  #ctrl{{background:#252526;border-top:1px solid #333;padding:8px 14px;
         display:flex;align-items:center;gap:10px;flex-shrink:0}}
  button{{background:#0e639c;color:#fff;border:none;padding:4px 13px;
          border-radius:3px;cursor:pointer;font:12px Consolas,monospace}}
  button:hover{{background:#1177bb}}
  button:disabled{{background:#333;color:#555;cursor:default}}
  #pbtn{{background:#16825d;min-width:68px}}
  #pbtn:hover{{background:#1a9068}}
  #pbtn.on{{background:#7a3010}}
  #pbtn.on:hover{{background:#933a14}}
  #sc{{flex:1;accent-color:#007acc}}
  label{{font-size:11px;color:#666}}
  select{{background:#3c3c3c;color:#ccc;border:1px solid #555;border-radius:3px;
          padding:2px 5px;font:11px Consolas,monospace}}

  /* ── keyboard hint ── */
  #hint{{font-size:10px;color:#444;margin-left:auto}}
</style>
</head>
<body>

<div id="hd">
  <h1>&#9654;&nbsp;Execution Trace</h1>
  <span id="badge" class="badge b-line">line</span>
  <span id="fn"></span>
  <span id="ctr">Step 1 / {total}</span>
</div>

<div id="main">
  <div id="cp">{code_html}</div>
  <div id="vp">
    <h2>Variables</h2>
    <div id="vc"></div>
  </div>
</div>

<div id="ctrl">
  <button id="pvbtn" onclick="go(cur-1)">&#9664; Prev</button>
  <button id="pbtn"  onclick="togglePlay()">&#9654; Play</button>
  <button id="nxbtn" onclick="go(cur+1)">Next &#9654;</button>
  <input  id="sc" type="range" min="0" max="{total - 1}" value="0"
          oninput="go(+this.value)">
  <label>Speed
    <select id="spd" onchange="setSpeed()">
      <option value="1400">Slow</option>
      <option value="750" selected>Normal</option>
      <option value="300">Fast</option>
      <option value="80">Very fast</option>
    </select>
  </label>
  <span id="hint">&#8592;&#8594; step &nbsp;|&nbsp; Space play</span>
</div>

<script>
const steps={steps_json};
const N=steps.length;
let cur=0,playing=false,timer=null,speed=750;

function typeName(v){{
  if(v===null)return'None';
  if(typeof v==='boolean')return'bool';
  if(typeof v==='number')return Number.isInteger(v)?'int':'float';
  if(typeof v==='string')return'str';
  if(Array.isArray(v))return`list[${{v.length}}]`;
  if(typeof v==='object')return'dict';
  return typeof v;
}}
function valClass(v){{
  if(typeof v==='number')return' num';
  if(typeof v==='boolean')return' bl';
  return'';
}}
function display(v){{
  if(typeof v==='string')return`"${{v}}"`;
  return JSON.stringify(v);
}}

function renderVars(step,prev){{
  const pl=prev?prev.locals:{{}};
  const vc=document.getElementById('vc');
  const loc=step.locals||{{}};
  const keys=Object.keys(loc);

  // badge + fn label
  const badge=document.getElementById('badge');
  badge.textContent=step.event;
  badge.className='badge b-'+step.event;
  document.getElementById('fn').textContent=
    step.function==='<module>'?'(module level)':'in '+step.function+'()';

  if(!keys.length && !step.retval && !step.error){{
    vc.innerHTML='<div class="empty">No local variables</div>';return;
  }}

  let h='';
  for(const[k,v]of Object.entries(loc)){{
    const changed=JSON.stringify(v)!==JSON.stringify(pl[k]);
    h+=`<div class="vr${{changed?' changed':''}}">
      <span class="vn">${{k}}</span>
      <span class="vt">${{typeName(v)}}</span>
      <span class="vv${{valClass(v)}}">${{display(v)}}</span>
    </div>`;
  }}
  if(step.retval!==null&&step.retval!==undefined)
    h+=`<div class="retbox">&#8617; return &nbsp;<span style="color:#ce9178">${{display(step.retval)}}</span></div>`;
  if(step.error)
    h+=`<div class="errbox">&#9888; ${{step.error}}</div>`;
  vc.innerHTML=h;
}}

function go(n){{
  if(n<0||n>=N)return;

  // un-highlight old line
  const old=steps[cur];
  if(old.lineno>0){{
    const el=document.getElementById('L'+old.lineno);
    if(el){{el.classList.remove('active');el.classList.add('visited');}}
  }}

  cur=n;
  const s=steps[cur];

  // highlight new line
  if(s.lineno>0){{
    const el=document.getElementById('L'+s.lineno);
    if(el){{
      el.classList.remove('visited');
      el.classList.add('active');
      el.scrollIntoView({{block:'nearest',behavior:'smooth'}});
    }}
  }}

  renderVars(s, n>0?steps[n-1]:null);
  document.getElementById('ctr').textContent='Step '+(n+1)+' / '+N;
  document.getElementById('sc').value=n;
  document.getElementById('pvbtn').disabled=n===0;
  document.getElementById('nxbtn').disabled=n===N-1;
  if(n===N-1&&playing)stopPlay();
}}

function togglePlay(){{playing?stopPlay():startPlay();}}
function startPlay(){{
  playing=true;
  const b=document.getElementById('pbtn');
  b.textContent='&#9646;&#9646; Pause';b.classList.add('on');
  timer=setInterval(()=>{{if(cur<N-1)go(cur+1);else stopPlay();}},speed);
}}
function stopPlay(){{
  playing=false;clearInterval(timer);
  const b=document.getElementById('pbtn');
  b.textContent='&#9654; Play';b.classList.remove('on');
}}
function setSpeed(){{
  speed=+document.getElementById('spd').value;
  if(playing){{stopPlay();startPlay();}}
}}

document.addEventListener('keydown',e=>{{
  if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
  if(e.key==='ArrowRight'||e.key==='l')go(cur+1);
  if(e.key==='ArrowLeft'||e.key==='h')go(cur-1);
  if(e.key===' '){{e.preventDefault();togglePlay();}}
}});

go(0);
</script>
</body>
</html>"""


# ── Public entry point ────────────────────────────────────────────────────────

def open_visualization(source: str, setup: str = "") -> str:
    """
    Trace *source*, write the HTML to a temp file, open it in VS Code's
    Simple Browser (or the system browser if VS Code isn't available).
    Returns the path to the generated HTML file.
    """
    steps = trace_code(source, setup)
    html = generate_html(source, steps)

    fd, path = tempfile.mkstemp(suffix=".html", prefix="mini_claude_trace_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)

    file_url = "file:///" + path.replace("\\", "/")

    # Try VS Code Simple Browser first (opens inside the editor)
    vscode_url = "vscode://vscode.simpleBrowser.show?url=" + urllib.parse.quote(
        file_url, safe=""
    )
    try:
        result = subprocess.run(
            ["code", "--open-url", vscode_url],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fall back to default system browser
    webbrowser.open(file_url)
    return path
