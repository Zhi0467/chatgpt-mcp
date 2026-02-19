from mcp.server.fastmcp import FastMCP
from chatgpt_mcp.mcp_tools import setup_mcp_tools

# Initialize the MCP server
mcp = FastMCP("chatgpt")

# Setup MCP tools
setup_mcp_tools(mcp)

def main():
    """Main entry point for the MCP server"""
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
