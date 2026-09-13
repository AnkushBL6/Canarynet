"""Independent wire-level fault fixture; intentionally violates MCP in test modes."""
import json
import os
import sys
import time

mode = sys.argv[1]
tool = {"name": "echo", "inputSchema": {"type": "object"}}


def send(value):
    print(json.dumps(value), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if "id" not in request:
        continue
    rid = request["id"]
    if method == "initialize":
        if mode == "timeout":
            time.sleep(30)
        if mode == "crash":
            sys.exit(4)
        if mode == "bad-json":
            print("not JSON", flush=True)
            continue
        if mode == "large-line":
            print("X" * 1_100_000, flush=True)
            continue
        result = {"protocolVersion": "2099-01-01" if mode == "bad-version" else "2025-11-25",
                  "capabilities": {} if mode == "no-tools" else {"tools": {}},
                  "serverInfo": {"name": "adversarial", "version": "test"}}
    elif method == "tools/list":
        if mode == "duplicate":
            result = {"tools": [tool, tool]}
        elif mode == "cursor-loop":
            result = {"tools": [], "nextCursor": "again"}
        elif mode == "pages":
            result = {"tools": [tool], "nextCursor": "second"} if not request["params"] else {"tools": [{"name": "second", "inputSchema": {"type": "object"}}]}
        else:
            result = {"tools": [tool]}
    elif method == "tools/call":
        if mode == "rpc-error":
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "SECRET_REMOTE_ERROR", "data": {"token": "SECRET_REMOTE_ERROR"}}})
            continue
        if mode == "call-timeout":
            time.sleep(30)
        if mode == "notify":
            send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "SECRET_LOG"}})
        if mode == "catalog-change":
            send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        if mode == "server-request":
            send({"jsonrpc": "2.0", "id": "server-1", "method": "sampling/createMessage", "params": {}})
            answer = json.loads(sys.stdin.readline())
            if answer.get("error", {}).get("code") != -32601:
                sys.exit(8)
            send({"jsonrpc": "2.0", "id": "ping-1", "method": "ping"})
            if json.loads(sys.stdin.readline()).get("result") != {}:
                sys.exit(9)
        result = {"content": [], "structuredContent": {"secret": os.environ.get("CANARY_TEST_SECRET", "not-inherited")}, "isError": False}
    else:
        result = {}
    if mode == "partial-line":
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}))
        sys.stdout.flush()
        sys.exit(0)
    if mode == "error-without-message":
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602}})
        continue
    if mode == "stderr":
        sys.stderr.write("SECRET_STDERR" * 10000)
        sys.stderr.flush()
    send({"jsonrpc": "2.0", "id": True if mode == "bool-id" else rid + 1 if mode == "wrong-id" else rid, "result": result})
