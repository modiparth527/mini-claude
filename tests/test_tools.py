"""
Unit tests for the tools module.

These tests exercise the Python implementations directly — no API calls,
no network, fast. The agent loop (which calls Claude) is tested separately
with integration tests that require a real API key.
"""

from pathlib import Path

from mini_claude.tools import execute_tool, list_files, read_file, run_bash, write_file

# ---------------------------------------------------------------------------
# read_file / write_file
# ---------------------------------------------------------------------------


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    content = "hello, world\n"

    result = write_file(str(target), content)
    assert "Wrote" in result
    assert read_file(str(target)) == content


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    write_file(str(target), "nested")
    assert target.exists()


def test_read_missing_file_returns_error() -> None:
    result = read_file("/nonexistent/path/file.txt")
    assert "Error" in result


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


def test_list_files_shows_entries(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x")
    (tmp_path / "bar").mkdir()

    result = list_files(str(tmp_path))
    assert "foo.py" in result
    assert "bar" in result


def test_list_files_empty_dir(tmp_path: Path) -> None:
    result = list_files(str(tmp_path))
    assert "empty" in result


def test_list_files_bad_path() -> None:
    result = list_files("/no/such/directory")
    assert "Error" in result


# ---------------------------------------------------------------------------
# run_bash
# ---------------------------------------------------------------------------


def test_run_bash_captures_stdout() -> None:
    result = run_bash("echo hello")
    assert "hello" in result


def test_run_bash_captures_stderr() -> None:
    result = run_bash("echo err >&2")
    assert "err" in result


def test_run_bash_nonzero_exit_still_returns_output() -> None:
    result = run_bash("exit 1")
    # Should not raise — just return whatever output exists
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# execute_tool dispatcher
# ---------------------------------------------------------------------------


def test_execute_tool_unknown_name() -> None:
    result = execute_tool("nonexistent_tool", {})
    assert "Unknown tool" in result


def test_execute_tool_dispatches_correctly(tmp_path: Path) -> None:
    path = str(tmp_path / "test.txt")
    write_result = execute_tool("write_file", {"path": path, "content": "hi"})
    assert "Wrote" in write_result

    read_result = execute_tool("read_file", {"path": path})
    assert read_result == "hi"
