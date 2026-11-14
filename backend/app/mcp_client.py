"""Official MCP Python SDK client for the local approved-action FastMCP server."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import DATA_DIR, GITHUB_WRITE_TOKEN


BACKEND_DIR = Path(__file__).resolve().parents[1]
TOOL_NAME = "execute_approved_github_action"


def _error_detail(error: BaseException) -> str:
    """Unwrap task-group errors so the MCP tool's actionable message is preserved."""
    nested = getattr(error, "exceptions", None)
    if nested:
        details = [_error_detail(item) for item in nested]
        return "; ".join(detail for detail in details if detail) or str(error)
    return str(error)


async def _call_approved_github_action(proposal_id: str, payload_hash: str):
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.github_mcp"],
        cwd=str(BACKEND_DIR),
        env={
            "CODEBASE_DATA_DIR": str(DATA_DIR),
            "GITHUB_WRITE_TOKEN": GITHUB_WRITE_TOKEN,
        },
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            available_tools = await session.list_tools()
            if not any(tool.name == TOOL_NAME for tool in available_tools.tools):
                raise RuntimeError("The FastMCP server did not expose the approved GitHub action tool.")
            result = await session.call_tool(
                TOOL_NAME,
                {"proposal_id": proposal_id, "payload_hash": payload_hash},
            )
            if result.isError:
                message = " ".join(
                    str(getattr(item, "text", "")) for item in result.content
                ).strip()
                raise RuntimeError(message or "The approved GitHub action failed in the MCP server.")
            structured = getattr(result, "structuredContent", None)
            if isinstance(structured, dict):
                return structured
            content = next(
                (str(getattr(item, "text", "")) for item in result.content if getattr(item, "text", None)),
                "",
            )
            if not content:
                raise RuntimeError("The MCP server returned no action result.")
            return json.loads(content)


def call_approved_github_action(proposal_id: str, payload_hash: str):
    try:
        return asyncio.run(_call_approved_github_action(proposal_id, payload_hash))
    except Exception as error:
        raise RuntimeError(
            "The local FastMCP action server could not complete the request: {}".format(_error_detail(error))
        ) from error
