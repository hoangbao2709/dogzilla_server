"""Backward-compatible entrypoint for the robot MCP server."""

from robot_mcp_server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
