"""MCP client side: connects the agent to our server and the third-party filesystem server over stdio.

The toolbox is the agent's ENTIRE reach into the world. It exposes no send/approve capability because
neither server has one, and it filters the filesystem server down to read-only tools.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from crop_pilot import config
from crop_pilot.core import telemetry
from crop_pilot.core.resilience import log_recovery

OUR_SERVER = "crop-pilot"
FS_SERVER = "filesystem"


class Toolbox:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, tuple[str, dict]] = {}   # tool name -> (server, json schema)
        self.degraded: list[str] = []
        self.recoveries: list[dict] = []

    async def _connect(self, stack: AsyncExitStack, name: str, params: StdioServerParameters,
                       allowed: set[str] | None = None) -> None:
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        self.sessions[name] = session
        for tool in listed.tools:
            if allowed is None or tool.name in allowed:
                self.tools[tool.name] = (name, {"description": tool.description or "", "parameters": tool.inputSchema})

    def ollama_specs(self, exclude: set[str] = frozenset()) -> list[dict]:
        return [{"type": "function", "function": {"name": n, **spec}}
                for n, (_, spec) in self.tools.items() if n not in exclude]

    async def call(self, tool: str, arguments: dict, actor: str = "agent") -> dict:
        if tool not in self.tools:
            out = {"ok": False, "error": f"tool {tool!r} does not exist. Available: {sorted(self.tools)}"}
            telemetry.record(self.run_id, "none", tool, arguments, out, latency_ms=0, status="blocked", actor=actor)
            return out
        server, _ = self.tools[tool]
        started = time.perf_counter()
        # Retry transport failures and timeouts (every write tool is idempotent per run, so a retry is safe).
        # A tool that answers ok=false is not retried: that is a real answer, not a fault.
        attempts, failures = 1 + config.TOOL_RETRIES, []
        for attempt in range(1, attempts + 1):
            try:
                result = await asyncio.wait_for(self.sessions[server].call_tool(tool, arguments),
                                                timeout=config.TOOL_TIMEOUT_S)
                out = _parse_result(result)
                status = "error" if result.isError or out.get("ok") is False else "ok"
                break
            except Exception as exc:  # noqa: BLE001 - a broken tool must not crash the run
                failures.append(f"{type(exc).__name__}: {exc}"[:200])
                out, status = {"ok": False, "error": failures[-1]}, "error"
                if attempt < attempts:
                    await asyncio.sleep(0.3 * attempt)
        if failures:
            event = log_recovery(self.run_id, f"mcp:{tool}", "; ".join(failures),
                                 "retried" if status == "ok" else "gave_up", None, len(failures) + (status == "ok"))
            self.recoveries.append(event)
        latency = (time.perf_counter() - started) * 1000
        out["_call_id"] = telemetry.record(self.run_id, server, tool, arguments, out,
                                           latency_ms=latency, status=status, actor=actor)
        return out


def _parse_result(result) -> dict:
    if getattr(result, "structuredContent", None):
        data = result.structuredContent
        # FastMCP wraps non-dict returns as {"result": ...}
        data = dict(data["result"]) if set(data) == {"result"} and isinstance(data["result"], dict) else dict(data)
        if isinstance(data.get("content"), str) and "text" not in data:   # filesystem server shape
            data["text"] = data.pop("content")[:6000]
        return data
    text = "\n".join(getattr(c, "text", "") for c in result.content or [])
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except ValueError:
        return {"ok": not result.isError, "text": text[:6000]} if not result.isError else {"ok": False, "error": text[:500]}


def _child_env() -> dict:
    env = dict(os.environ)
    backend_dir = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = backend_dir + os.pathsep + env.get("PYTHONPATH", "")
    env["CROP_PILOT_DB"] = str(config.DB_PATH)
    return env


@asynccontextmanager
async def open_toolbox(run_id: str, with_filesystem: bool = True):
    tb = Toolbox(run_id)
    async with AsyncExitStack() as stack:
        await tb._connect(stack, OUR_SERVER, StdioServerParameters(
            command=sys.executable, args=["-m", "crop_pilot.mcp_server.server"], env=_child_env()))
        if with_filesystem:
            npx = shutil.which("npx")
            if npx is None:
                tb.degraded.append("third_party_mcp_unavailable: npx not found")
            else:
                try:
                    await tb._connect(stack, FS_SERVER, StdioServerParameters(
                        command=npx, args=["-y", config.FS_MCP_PACKAGE, str(config.REFERENCE_DIR)],
                        env=_child_env()), allowed=config.FS_MCP_ALLOWED_TOOLS)
                except Exception as exc:  # noqa: BLE001
                    tb.degraded.append(f"third_party_mcp_unavailable: {type(exc).__name__}")
        yield tb
