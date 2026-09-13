import asyncio
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from canarynet.cli import init, main
from canarynet.common import CanaryError, canonical, digest, load_config, loads, pointer, read_json, same_json, write_json
from canarynet.engine import STATUSES, check, classify, surface_diff
from canarynet.schema import SchemaOracle
from canarynet.transport import RpcError, StdioClient, TransportError

FIXTURES = Path(__file__).parent / "fixtures"


class JSONTests(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(CanaryError):
            loads('{"a":1,"a":2}')

    def test_nonfinite_rejected(self):
        for text in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(text=text), self.assertRaises(CanaryError):
                loads(text)

    def test_size_rejected(self):
        with self.assertRaises(CanaryError):
            loads('"' + 'a' * 1_048_576 + '"')

    def test_depth_rejected(self):
        with self.assertRaises(CanaryError):
            loads('[' * 100 + '0' + ']' * 100)

    def test_invalid_json(self):
        with self.assertRaises(CanaryError):
            loads(b'\xff')

    def test_pointer_escaping(self):
        self.assertEqual(pointer({"a/b": {"~": [None]}}, "/a~1b/~0/0"), (True, None))

    def test_pointer_missing_is_not_null(self):
        self.assertEqual(pointer({"x": None}, "/x"), (True, None))
        self.assertEqual(pointer({}, "/x"), (False, None))

    def test_pointer_rejects_bad_escapes(self):
        with self.assertRaises(CanaryError):
            pointer({}, "/~2")

    def test_pointer_rejects_leading_zero_and_negative_index(self):
        for key in ("/01", "/-1", "/-"):
            self.assertEqual(pointer([0, 1], key), (False, None))

    def test_json_equality(self):
        self.assertFalse(same_json(True, 1))
        self.assertTrue(same_json(1.0, 1))
        self.assertTrue(same_json({"a": [2]}, {"a": [2.0]}))
        self.assertFalse(same_json({"a": 1}, {"b": 1}))

    def test_canonical_fingerprint(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        init(self.root)
        self.path = self.root / "canarynet.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_demo_loads(self):
        self.assertEqual(len(load_config(self.path)["cases"]), 4)

    def test_init_does_not_overwrite(self):
        before = (self.root / "server.py").read_bytes()
        with self.assertRaises(CanaryError):
            init(self.root)
        self.assertEqual(before, (self.root / "server.py").read_bytes())

    def test_rejects_bad_config(self):
        original = read_json(self.path)
        mutations = [
            lambda c: c.update(version=True), lambda c: c.update(repetitions=1),
            lambda c: c.update(repetitions=True), lambda c: c.update(timeoutSeconds=-1),
            lambda c: c.update(allowTools=[]), lambda c: c.update(contracts=["../*.json"]),
            lambda c: c.update(contracts=["missing*.json"]), lambda c: c.update(extra=True),
            lambda c: c["baseline"].update(command="echo hi"),
            lambda c: c["baseline"].update(envAllow=["TOKEN=value"]),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = copy.deepcopy(original)
                mutate(changed)
                write_json(self.path, changed)
                with self.assertRaises(CanaryError):
                    load_config(self.path)

    def test_no_unallowlisted_tool(self):
        config = read_json(self.path)
        config["allowTools"] = ["lookup"]
        write_json(self.path, config)
        with self.assertRaises(CanaryError):
            load_config(self.path)

    def test_duplicate_case_rejected(self):
        path = self.root / "contracts/cart.json"
        contract = read_json(path)
        contract["cases"].append(contract["cases"][0])
        write_json(path, contract)
        with self.assertRaises(CanaryError):
            load_config(self.path)

    def test_expectation_explicit(self):
        path = self.root / "contracts/cart.json"
        contract = read_json(path)
        del contract["cases"][0]["expect"]["isError"]
        write_json(path, contract)
        with self.assertRaises(CanaryError):
            load_config(self.path)

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as external:
            other = Path(external) / "other.json"
            other.write_text('{}')
            (self.root / "contracts/escape.json").symlink_to(other)
            with self.assertRaises(CanaryError):
                load_config(self.path)

    def test_execution_requires_acknowledgement(self):
        with self.assertRaises(CanaryError):
            asyncio.run(check(load_config(self.path)))


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = SchemaOracle().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.oracle.__exit__()

    def test_type_error_has_no_payload(self):
        result = self.oracle.validate({"type": "integer"}, "SECRET_123")
        self.assertEqual(result, [{"code": "type", "path": ""}])
        self.assertNotIn("SECRET", canonical(result))

    def test_required_nullable_and_enum(self):
        schema = {"type": "object", "required": ["status"], "properties": {"status": {"enum": [None, "ok"]}}}
        self.assertEqual(self.oracle.validate(schema, {"status": None}), [])
        self.assertEqual(self.oracle.validate(schema, {"status": "ok"}), [])
        self.assertTrue(self.oracle.validate(schema, {}))
        self.assertTrue(self.oracle.validate(schema, {"status": "no"}))

    def test_local_ref(self):
        schema = {"$defs": {"number": {"type": "integer"}}, "$ref": "#/$defs/number"}
        self.assertEqual(self.oracle.validate(schema, 4), [])
        self.assertTrue(self.oracle.validate(schema, "4"))

    def test_external_references_fail_closed(self):
        for ref in ("https://example.com/schema", "file:///etc/passwd", "relative.json"):
            with self.subTest(ref=ref), self.assertRaises(CanaryError):
                self.oracle.validate({"$ref": ref}, {})

    def test_unsupported_dialect(self):
        with self.assertRaises(CanaryError):
            self.oracle.validate({"$schema": "http://json-schema.org/draft-07/schema#"}, {})

    def test_invalid_schema(self):
        with self.assertRaises(CanaryError):
            self.oracle.validate({"type": "not-a-type"}, {})

    def test_invalid_local_reference(self):
        with self.assertRaises(CanaryError):
            self.oracle.validate({"$ref": "#/$defs/missing"}, {})

    def test_combinators_and_additional_properties(self):
        self.assertEqual(self.oracle.validate({"oneOf": [{"type": "string"}, {"type": "integer"}]}, 3), [])
        self.assertTrue(self.oracle.validate({"type": "object", "additionalProperties": False}, {"x": 1}))

    def test_validation_deadline(self):
        # An adversarial regular expression must not hang the parent process.
        with SchemaOracle(timeout=1.0) as oracle:
            oracle.validate({"type": "string"}, "warmup")
            with self.assertRaises(CanaryError):
                oracle.validate({"type": "string", "pattern": "^(a+)+$"}, "a" * 30 + "!")


class ClassificationTests(unittest.TestCase):
    def sample(self, state):
        return {"state": state, "issues": []}

    def test_all_combinations(self):
        expected = {("pass", "pass"): "compatible", ("pass", "fail"): "regression", ("fail", "pass"): "improvement", ("fail", "fail"): "baseline_failure"}
        for (a, b), status in expected.items():
            with self.subTest(a=a, b=b):
                self.assertEqual(classify([self.sample(a)] * 2, [self.sample(b)] * 2), status)

    def test_errors_are_inconclusive(self):
        self.assertEqual(classify([self.sample("pass")] * 2, [self.sample("error")] * 2), "inconclusive")

    def test_errors_take_priority_over_instability(self):
        self.assertEqual(classify([self.sample("pass"), self.sample("fail")], [self.sample("error")] * 2), "inconclusive")

    def test_changing_outcomes_are_unstable(self):
        self.assertEqual(classify([self.sample("pass")] * 2, [self.sample("pass"), self.sample("fail")]), "unstable")

    def test_empty_and_partial_runs_are_inconclusive(self):
        self.assertEqual(classify([], []), "inconclusive")
        self.assertEqual(classify([self.sample("pass")], [self.sample("pass")] * 2), "inconclusive")

    def test_surface_change_never_proves_compatibility(self):
        before = {"x": {"name": "x", "inputSchema": {"type": "object"}}}
        after = copy.deepcopy(before)
        after["x"]["inputSchema"]["properties"] = {"optional": {"type": "string"}}
        self.assertEqual(surface_diff(before, after)[0]["severity"], "review")

    def test_surface_add_remove_and_identical(self):
        tool = {"x": {"name": "x", "inputSchema": {}}}
        self.assertEqual(surface_diff(tool, tool), [])
        self.assertEqual(surface_diff({}, tool)[0]["severity"], "info")
        self.assertEqual(surface_diff(tool, {})[0]["severity"], "breaking")


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def client(self, mode, **kwargs):
        return StdioClient({"command": ["{python}", str(FIXTURES / "adversarial_server.py"), mode], **kwargs}, 1.5)

    async def test_protocol_faults(self):
        for mode in ("timeout", "crash", "bad-json", "large-line", "bad-version", "no-tools", "bool-id", "wrong-id", "partial-line", "error-without-message"):
            with self.subTest(mode=mode), self.assertRaises(TransportError):
                async with self.client(mode):
                    pass

    async def test_pagination(self):
        async with self.client("pages") as client:
            self.assertEqual(set(await client.tools()), {"echo", "second"})

    async def test_duplicate_tools_and_cursor_loop(self):
        for mode in ("duplicate", "cursor-loop"):
            with self.subTest(mode=mode):
                async with self.client(mode) as client:
                    with self.assertRaises(TransportError):
                        await client.tools()

    async def test_notifications_stderr_and_server_requests(self):
        for mode in ("notify", "stderr", "server-request"):
            with self.subTest(mode=mode):
                async with self.client(mode) as client:
                    result = await client.request("tools/call", {"name": "echo", "arguments": {}})
                    self.assertFalse(result["isError"])

    async def test_call_timeout(self):
        async with self.client("call-timeout") as client:
            with self.assertRaises(TransportError):
                await client.request("tools/call", {"name": "echo", "arguments": {}})

    async def test_error_payload_is_not_returned(self):
        async with self.client("rpc-error") as client:
            with self.assertRaises(RpcError) as caught:
                await client.request("tools/call", {"name": "echo", "arguments": {}})
            self.assertNotIn("SECRET", str(caught.exception))

    async def test_environment_is_explicit(self):
        with patch.dict(os.environ, {"CANARY_TEST_SECRET": "EXPLICIT_SECRET"}):
            async with self.client("normal") as client:
                result = await client.request("tools/call", {"name": "echo", "arguments": {}})
                self.assertEqual(result["structuredContent"]["secret"], "not-inherited")
            async with self.client("normal", envAllow=["CANARY_TEST_SECRET"]) as client:
                result = await client.request("tools/call", {"name": "echo", "arguments": {}})
                self.assertEqual(result["structuredContent"]["secret"], "EXPLICIT_SECRET")

    async def test_catalog_change_flag(self):
        async with self.client("catalog-change") as client:
            await client.request("tools/call", {"name": "echo", "arguments": {}})
            self.assertTrue(client.catalog_changed)

    @unittest.skipUnless(importlib.util.find_spec("mcp") is not None, "Official MCP SDK is not installed in this environment")
    async def test_official_sdk_interoperability(self):
        async with StdioClient({"command": ["{python}", str(FIXTURES / "sdk_server.py")]}, 10) as client:
            tools = await client.tools()
            self.assertIn("add", tools)
            result = await client.request("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}})
            self.assertEqual(result["structuredContent"]["sum"], 5)


if __name__ == "__main__":
    unittest.main()
