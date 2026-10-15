"""Architecture boundaries, checked statically so they cannot silently regress."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_IN_AGENT_SIDE = ("crop_pilot.dispatch", "smtplib", "twilio", "africastalking", "requests")


def _imports(folder: Path) -> set[str]:
    names = set()
    for py in folder.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
    return names


def test_agent_and_mcp_server_cannot_reach_dispatch_or_network_senders():
    for pkg in ("agent", "mcp_server", "core"):
        imported = _imports(ROOT / "backend" / "crop_pilot" / pkg)
        bad = {m for m in imported if m.startswith(FORBIDDEN_IN_AGENT_SIDE)}
        assert not bad, f"{pkg} imports {bad}"


def test_frontend_never_imports_backend():
    imported = _imports(ROOT / "frontend")
    assert not {m for m in imported if m.startswith(("crop_pilot", "sqlite3", "langgraph", "mcp"))}


def test_mcp_server_exposes_no_send_tool():
    from crop_pilot.mcp_server.server import mcp
    import asyncio
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {"get_rainfall_outlook", "get_plot_context", "get_pest_reports", "draft_advisory"}
