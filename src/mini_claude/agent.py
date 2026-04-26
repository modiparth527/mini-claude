"""
Agent loop — the core of the application.

The loop sends messages to Claude, handles tool calls, and feeds results
back until Claude returns a plain-text response with no further tool calls.

Keeping this module free of CLI/UI concerns (no typer, no sys.exit) makes
it easy to test and reuse in other contexts (e.g. a web server, a test
harness, a batch script).
"""

import json
import logging
from typing import Any

import anthropic
from rich.console import Console

from mini_claude.config import Settings
from mini_claude.tools import TOOLS, execute_tool

log = logging.getLogger(__name__)

# Type alias for readability
Message = dict[str, Any]

# Both Anthropic and AnthropicBedrock inherit from this base — accepting either
_AnyClient = anthropic.Anthropic | anthropic.AnthropicBedrock


def run_agent(
    *,
    user_message: str,
    history: list[Message],
    client: _AnyClient,
    settings: Settings,
    console: Console,
) -> list[Message]:
    """
    Append user_message to history, drive the tool-call loop until Claude
    returns a text-only response, then return the updated history.

    Parameters are keyword-only (the * forces it) — production practice that
    prevents silent argument-order bugs when callers add new params.
    """
    history.append({"role": "user", "content": user_message})

    while True:
        printed_text = False

        # -- Stream the response so text appears token-by-token --------------
        with client.messages.stream(
            model=settings.effective_model,
            max_tokens=settings.max_tokens,
            system=settings.system_prompt,
            tools=TOOLS,
            messages=history,
        ) as stream:
            for text in stream.text_stream:
                console.print(text, end="")
                printed_text = True

            message = stream.get_final_message()

        if printed_text:
            console.print()  # newline after streamed text

        log.debug(
            "api_response",
            extra={
                "stop_reason": message.stop_reason,
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            },
        )

        # -- Build the assistant turn for history ----------------------------
        assistant_content: list[dict[str, Any]] = []
        tool_calls: list[Any] = []

        for block in message.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
                tool_calls.append(block)

        history.append({"role": "assistant", "content": assistant_content})

        # -- No tool calls → done --------------------------------------------
        if not tool_calls:
            break

        # -- Execute tools and collect results --------------------------------
        tool_results: list[dict[str, Any]] = []
        for call in tool_calls:
            console.print(
                f"\n[bold yellow]  tool:[/bold yellow] {call.name} "
                f"[dim]{json.dumps(call.input)}[/dim]"
            )
            result = execute_tool(call.name, call.input)
            log.debug("tool_result", extra={"tool": call.name, "result_len": len(result)})

            preview = result[:300] + ("…" if len(result) > 300 else "")
            console.print(f"[bold green]result:[/bold green] {preview}")

            tool_results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": result}
            )

        # Feed results back so Claude can continue reasoning
        history.append({"role": "user", "content": tool_results})

    return history
