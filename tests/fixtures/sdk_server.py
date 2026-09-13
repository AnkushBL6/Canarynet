"""Independent interoperability fixture using the official MCP Python SDK v1.x."""
from mcp.server.fastmcp import FastMCP

app = FastMCP("canarynet-sdk-interoperability")


@app.tool()
def add(a: int, b: int) -> dict[str, int]:
    """Add two integers using an independently implemented MCP server."""
    return {"sum": a + b}


if __name__ == "__main__":
    app.run(transport="stdio")
