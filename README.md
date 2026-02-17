# ChatGPT MCP Server

A Model Context Protocol (MCP) server that enables AI assistants to interact with the ChatGPT desktop app on macOS.

<a href="https://glama.ai/mcp/servers/@xncbf/chatgpt-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@xncbf/chatgpt-mcp/badge" alt="ChatGPT Server MCP server" />
</a>

https://github.com/user-attachments/assets/a30c9b34-cdbe-4c0e-a0b0-33eb5054db5c

## Language Support

**Supported system languages for response detection:**
- Korean
- English

**If your macOS system language is not listed above, please follow these instructions:**
1. Make sure ChatGPT desktop app is running
2. Run `show_all_button_names.applescript` and copy the output to create an issue for language support.

## Features

- Send prompts to ChatGPT from any MCP-compatible AI assistant
- Built with Python and FastMCP

**Note:** This server only supports English text input. Non-English characters may not work properly.

## Installation

### Prerequisites
- macOS
- ChatGPT desktop app installed and running
- Python 3.10+
- uv package manager

## For Claude Code Users

Simply run:
```bash
claude mcp add chatgpt-mcp uvx chatgpt-mcp
```

That's it! You can start using ChatGPT commands in Claude Code.

## For Codex Users

Use a stable local install path instead of a transient `uvx` cache path.

### Step 1: Install the MCP server in a dedicated venv

```bash
python3 -m venv ~/.local/opt/chatgpt-mcp
~/.local/opt/chatgpt-mcp/bin/pip install "git+https://github.com/<your-github-user>/chatgpt-mcp.git@<commit-or-tag>"
```

### Step 2: Configure Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.chatgpt]
command = "/Users/<your-user>/.local/opt/chatgpt-mcp/bin/chatgpt-mcp"
args = []
tool_timeout_sec = 300
```

### Step 3: Restart Codex

Codex must be restarted after config changes so the new MCP command is loaded.

### Step 4: Verify MCP wiring

```bash
codex mcp get chatgpt
```

Then run a tiny tool call in Codex such as:
- `Reply with exactly: OK.`

If you still see transport disconnects, capture fresh MCP stderr from the failing run and confirm the configured command path still exists.

## For Other MCP Clients

### Step 1: Install the MCP Server

#### Option A: Install from PyPI (Recommended)
```bash
# Install with uv
uv add chatgpt-mcp
```

#### Option B: Manual Installation
```bash
# Clone the repository
git clone https://github.com/xncbf/chatgpt-mcp
cd chatgpt-mcp

# Install dependencies with uv
uv sync
```

### Step 2: Configure Your MCP Client

If installed from PyPI, add to your MCP client configuration:
```json
{
  "mcpServers": {
    "chatgpt": {
      "command": "uvx",
      "args": ["chatgpt-mcp"]
    }
  }
}
```

If manually installed, add to your MCP client configuration:
```json
{
  "mcpServers": {
    "chatgpt": {
      "command": "uv",
      "args": ["run", "chatgpt-mcp"],
      "cwd": "/path/to/chatgpt-mcp"
    }
  }
}
```

## Usage

1. **Open ChatGPT desktop app** and make sure it's running
2. **Open your MCP client** (Claude Code, etc.)
3. **Use ChatGPT commands** in your AI assistant:
   - "Send a message to ChatGPT"

The AI assistant will automatically use the appropriate MCP tools to interact with ChatGPT.

## Available Tools

### ask_chatgpt
Send a prompt to ChatGPT and receive the response.

```python
ask_chatgpt(prompt="Hello, ChatGPT!")
```

### get_chatgpt_response
Get the latest response from ChatGPT after sending a message.

```python
get_chatgpt_response()
```

### new_chatgpt_chat
Start a new chat conversation in ChatGPT.

```python
new_chatgpt_chat()
```

## Development

### Local Testing

To test the MCP server locally during development:

1. **Install in editable mode**
   ```bash
   uv pip install -e .
   ```

2. **Test with MCP Inspector**
   ```bash
   npx @modelcontextprotocol/inspector chatgpt-mcp
   ```

The editable installation creates a `chatgpt-mcp` command that directly references your source code, so any changes you make are immediately reflected without reinstalling.

### Running without installation

You can also run the server directly:
```bash
PYTHONPATH=. uv run python -m chatgpt_mcp.chatgpt_mcp
```

## License

MIT
