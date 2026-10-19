"""Run a book-agent MCP tool in a fresh Python process, so code changes in
mcp_server.py / tools/ apply before the MCP server is restarted.

Usage (from this folder):
  python mcp_cli.py docx_append '{"project": "...", "blocks_file": "...", "chapter": "2", "section": "r02"}'
  python mcp_cli.py validate_blocks '{"project": "...", "blocks_file": "..."}'
"""
import asyncio
import inspect
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import mcp_server  # noqa: E402  (importing does not start the server)

name, args = sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
fn = getattr(mcp_server, name)
fn = getattr(fn, "fn", fn)  # some FastMCP versions wrap the function
res = asyncio.run(fn(**args)) if inspect.iscoroutinefunction(fn) else fn(**args)
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
