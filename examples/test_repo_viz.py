"""
Standalone test for the repo visualizer.
No AWS credentials or API key needed -- uses the mock client internally.
Run: .venv/Scripts/python test_repo_viz.py
"""

import sys
from pathlib import Path

# Make sure src/ is on sys.path when run directly (not via poetry run)
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mini_claude.repo_tracer import open_repo_visualization, trace_repo, generate_repo_html
from mini_claude.repo_tracer import _Message, _TextBlock, _ToolUseBlock, _Usage


def _build_mock_responses() -> list[_Message]:
    return [
        _Message(
            stop_reason="tool_use",
            content=[_ToolUseBlock(id="toolu_t01", name="list_files", input={"path": "."})],
        ),
        _Message(
            stop_reason="end_turn",
            content=[_TextBlock(text="Here are the files.\nDone.")],
        ),
    ]


def test_trace_produces_steps() -> None:
    responses = _build_mock_responses()
    steps, sources = trace_repo("list the files here", responses=responses)

    assert len(steps) > 0, "Expected at least one trace step"
    assert len(sources) > 0, "Expected at least one source file captured"

    for step in steps:
        assert "filename" in step
        assert "lineno" in step
        assert "event" in step
        assert step["event"] in ("line", "call", "return", "exception")

    print(f"  steps    : {len(steps)}")
    print(f"  files    : {list(sources.keys())}")
    print("  PASS test_trace_produces_steps")


def test_generate_html() -> None:
    responses = _build_mock_responses()
    steps, sources = trace_repo("list the files here", responses=responses)
    html = generate_repo_html(sources, steps)

    assert "<!DOCTYPE html>" in html
    assert "switchFile" in html
    assert len(html) > 5_000, "HTML seems too small — likely missing content"

    # Each source file should have a tab
    for fname in sources:
        assert fname in html, f"Missing tab/panel for {fname}"

    print(f"  html size: {len(html):,} bytes")
    print("  PASS test_generate_html")


def test_open_visualization_creates_file() -> None:
    path = open_repo_visualization("list the files here")
    p = Path(path)

    assert p.exists(), f"Expected HTML file at {path}"
    assert p.suffix == ".html"
    assert p.stat().st_size > 1_000

    print(f"  opened   : {path}")
    print("  PASS test_open_visualization_creates_file")


if __name__ == "__main__":
    print("\nRunning repo visualizer tests...\n")
    try:
        test_trace_produces_steps()
        test_generate_html()
        test_open_visualization_creates_file()
        print("\nAll tests passed.")
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)
