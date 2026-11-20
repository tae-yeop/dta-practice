"""Real MCP transport test; may use a separate MCP Python environment."""

import asyncio
import os
from pathlib import Path
import sys

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT = Path(__file__).resolve().parents[1]
from dti_tool.models import MODELS


def test_mcp_discovery_and_error_contract(tmp_path):
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable, args=[str(PROJECT / "scripts" / "serve_mcp.py")],
            env={**os.environ, "DTI_MODEL_CACHE": str(tmp_path / "empty")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert [item.name for item in listed.tools] == ["predict_dta", "profile_input"]
                profile = await session.call_tool("profile_input", {"smiles": "CCO", "protein_sequence": "ACDEFGHIK"})
                assert not profile.isError and profile.structuredContent["compound"]["formula"] == "C2H6O"
                assert listed.tools[0].inputSchema["additionalProperties"] is False
                assert listed.tools[0].inputSchema["properties"]["models"]["items"]["enum"] == list(MODELS)
                missing = await session.call_tool("predict_dta", {"smiles": "CCO", "protein_sequence": "ACDEFGHIK"})
                assert missing.isError
                assert missing.structuredContent["error"]["code"] == "MODEL_NOT_READY"
                assert missing.structuredContent["prediction"] is None
                from dti_tool.runs import get_run
                trace = get_run(missing.structuredContent["trace"]["run_id"])
                assert trace["source"] == "mcp"
                assert [event["event"] for event in trace["events"]] == [
                    "request.received", "skill.loaded", "profile.completed", "tool.started", "tool.failed", "run.failed"]
                unknown = await session.call_tool("predict_dta", {"smiles": "CCO", "protein_sequence": "ACDEFGHIK", "extra": 1})
                assert unknown.isError
                assert unknown.structuredContent["error"]["code"] == "INVALID_ARGUMENT"
                comparison = await session.call_tool("predict_dta", {"smiles": "CCO", "protein_sequence": "ACDEFGHIK",
                                                    "models": ["CNN_CNN_BindingDB", "MPNN_CNN_BindingDB"]})
                assert comparison.isError
                assert comparison.structuredContent["summary"] == {"succeeded": 0, "failed": 2}
    asyncio.run(exercise())
