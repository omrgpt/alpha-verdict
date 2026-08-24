# MCP server: verdicts for AI agents

AlphaVerdict ships a dependency-free [Model Context Protocol](https://modelcontextprotocol.io)
server over stdio. Any agent runtime — Claude Desktop, Claude Code, Codex, or a
custom client — can request deterministic research verdicts without a model ever
entering the ranking loop.

The server implements the MCP stdio transport (newline-delimited JSON-RPC 2.0)
using only the Python standard library, so installing `alphaverdict` is enough.

## Start the server

```bash
alphaverdict mcp
# or equivalently
python -m alphaverdict.mcp_server
```

## Register with an MCP client

Claude Desktop / `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "alphaverdict": {
      "command": "uvx",
      "args": ["alphaverdict", "mcp"]
    }
  }
}
```

Claude Code:

```bash
claude mcp add alphaverdict -- uvx alphaverdict mcp
```

## Tools

| Tool | Input | Behaviour |
| --- | --- | --- |
| `run_demo_verdict` | `{fast?: boolean}` | Runs the full pipeline on clearly labelled synthetic data and returns the merged verdict. |
| `run_project_verdict` | `{project_path: string, fast?: boolean}` | Backtests and audits one trusted local project directory (must contain `alphaverdict.yml`). Writes the standard artifact bundle and returns the verdict summary plus the report path. |
| `run_screen` | `{project_path: string, as_of?: string}` | Ranks the project's universe at one point in time and returns the top rows with scores. |
| `explain_finding` | `{code: string}` | Returns the stable explanation and remediation for one finding code (for example `COST_FRAGILE`). |
| `list_findings` | `{}` | Lists every finding code the council can emit. |

Tool errors are returned as MCP results with `isError: true`; malformed JSON-RPC
maps to the standard `-32700`, `-32600`, `-32601`, and `-32603` error codes.
Requests larger than 1 MiB are rejected without parsing. Protocol versions
`2025-06-18`, `2025-03-26`, and `2024-11-05` are supported during initialization
negotiation.

## Environment hardening

| Variable | Effect |
| --- | --- |
| `ALPHAVERDICT_MCP_ROOT` | When set, `project_path` arguments must resolve inside this directory; anything else raises a security-boundary error result. Recommended for any shared or hosted setup. |
| `ALPHAVERDICT_MCP_DEBUG` | Set to `1` to trace each request/response pair (truncated) to stderr. |

## Security posture

- The server is read-only with respect to the world: it writes only the standard
  run artifacts inside each project's configured output directory.
- Project strategies and adapters execute trusted local Python exactly as they do
  through the CLI; never point `run_project_verdict` at an untrusted repository
  without reviewing its configuration first.
- No model sees raw prices, credentials, or strategy source. The council is fully
  deterministic, so the same inputs always produce the same verdict.
