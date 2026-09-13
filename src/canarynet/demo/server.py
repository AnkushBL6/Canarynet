"""Synthetic MCP stdio server. No credentials, network, or business side effects.

The candidate changes behavior without changing its schema. This is intentional:
a schema diff alone cannot detect the failed consumer assertion.
"""
import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "baseline"
TOOLS = [
    {"name": "add", "description": "Add two integer values.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"], "additionalProperties": False},
     "outputSchema": {"type": "object", "properties": {"sum": {"type": "integer"}}, "required": ["sum"]}},
    {"name": "lookup", "description": "Read a synthetic inventory record.",
     "inputSchema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]},
     "outputSchema": {"type": "object", "properties": {"quantity": {"type": "integer"}}, "required": ["quantity"]}},
    {"name": "health", "description": "Unused synthetic tool demonstrating an explicit coverage gap.",
     "inputSchema": {"type": "object"}},
]
if MODE == "schema-break":
    TOOLS[0]["inputSchema"]["properties"]["currency"] = {"type": "string"}
    TOOLS[0]["inputSchema"]["required"].append("currency")
if MODE == "removed-tool":
    TOOLS = [tool for tool in TOOLS if tool["name"] != "add"]
if MODE == "review":
    TOOLS[0]["description"] = "Add two numbers; revised description affects model-visible metadata."


def reply(request, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": request["id"]}
    response["error" if error is not None else "result"] = error if error is not None else result
    print(json.dumps(response, separators=(",", ":")), flush=True)


initialized = False
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "notifications/initialized":
        initialized = True
        continue
    if "id" not in request:
        continue
    if method == "initialize":
        reply(request, {"protocolVersion": "2025-11-25", "serverInfo": {"name": "canarynet-synthetic", "version": MODE}, "capabilities": {"tools": {}}})
    elif not initialized:
        reply(request, error={"code": -32000, "message": "Initialization required"})
    elif method == "tools/list":
        reply(request, {"tools": TOOLS})
    elif method == "tools/call":
        params = request["params"]
        if params["name"] == "add":
            value = params["arguments"]["a"] + params["arguments"]["b"]
            if MODE == "breaking":
                value -= 1
            value = str(value) if MODE == "output-invalid" else value
            data = {"sum": value}
            reply(request, {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": False})
        elif params["name"] == "lookup":
            if params["arguments"]["sku"] == "UNKNOWN":
                reply(request, {"content": [{"type": "text", "text": "Synthetic record not found"}], "isError": True})
            else:
                data = {"quantity": 7}
                reply(request, {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": False})
        else:
            reply(request, error={"code": -32602, "message": "Unknown synthetic tool"})
    elif method == "ping":
        reply(request, {})
    else:
        reply(request, error={"code": -32601, "message": "Unsupported method"})
