"""FastMCP stdio server for hash-checked, explicitly approved GitHub actions."""
from mcp.server.fastmcp import FastMCP

from .github_actions import execute_approved_action


mcp = FastMCP(
    "codebase-whisperer-github-actions",
    instructions=(
        "Executes only locally stored issue, draft pull request, or reviewed code-fix proposals "
        "that have an approved status and matching review hash."
    ),
)


@mcp.tool()
def execute_approved_github_action(proposal_id: str, payload_hash: str) -> dict:
    """Execute one locally reviewed GitHub proposal after its approval hash is checked."""
    return execute_approved_action(proposal_id, payload_hash)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
