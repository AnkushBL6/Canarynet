"""Offline JSON Schema validation in a deadline-bounded worker process."""
from __future__ import annotations

import multiprocessing as mp
from typing import Any

from .common import CanaryError, MAX_BYTES, bounded, canonical

DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _guard(value: Any) -> None:
    if isinstance(value, dict):
        if "$schema" in value and value["$schema"] not in (DIALECT, DIALECT + "#"):
            raise CanaryError("unsupported_schema_dialect")
        for key in ("$ref", "$dynamicRef"):
            if key in value and (not isinstance(value[key], str) or not value[key].startswith("#")):
                raise CanaryError("external_schema_reference_blocked")
        for child in value.values():
            _guard(child)
    elif isinstance(value, list):
        for child in value:
            _guard(child)


def _deny_retrieval(uri: str) -> Any:
    from referencing.exceptions import NoSuchResource
    raise NoSuchResource(ref=uri)


def _worker(connection: Any) -> None:
    from jsonschema import Draft202012Validator
    from referencing import Registry

    cache: dict[str, Any] = {}
    connection.send({"ready": True})
    try:
        while True:
            request = connection.recv()
            if request is None:
                break
            schema, value, check_only = request
            try:
                _guard(schema)
                key = canonical(schema)
                if key not in cache:
                    Draft202012Validator.check_schema(schema)
                    if len(cache) >= 128:
                        cache.clear()
                    cache[key] = Draft202012Validator(schema, registry=Registry(retrieve=_deny_retrieval))
                issues = []
                if not check_only:
                    for error in cache[key].iter_errors(value):
                        # Never return validation messages, instances, or expected values.
                        path = "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in error.absolute_path)
                        issues.append({"code": str(error.validator), "path": path if error.absolute_path else ""})
                        if len(issues) == 8:
                            break
                connection.send({"issues": issues})
            except CanaryError as exc:
                connection.send({"error": str(exc)})
            except Exception:
                connection.send({"error": "invalid_or_unresolvable_schema"})
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


class SchemaOracle:
    """A timeout or invalid/unsupported schema is an error, NEVER a pass."""

    def __init__(self, timeout: float = 3.0) -> None:
        self.timeout = timeout
        self.process = None
        self.connection = None

    def __enter__(self) -> "SchemaOracle":
        parent, child = mp.get_context("spawn").Pipe()
        self.connection = parent
        self.process = mp.get_context("spawn").Process(target=_worker, args=(child,), daemon=True)
        self.process.start()
        child.close()
        # Interpreter/library startup is separate from the per-validation deadline.
        if not parent.poll(10):
            self.process.terminate()
            self.process.join(timeout=1)
            parent.close()
            raise CanaryError("schema_validator_startup_failed")
        try:
            ready = parent.recv()
        except EOFError as exc:
            self.process.join(timeout=1)
            parent.close()
            raise CanaryError("schema_validator_startup_failed") from exc
        if ready != {"ready": True}:
            self.__exit__()
            raise CanaryError("schema_validator_startup_failed")
        return self

    def validate(self, schema: Any, value: Any = None, *, check_only: bool = False) -> list[dict]:
        bounded(schema)
        bounded(value)
        if len(canonical([schema, value])) > MAX_BYTES:
            raise CanaryError("schema_validation_input_too_large")
        if self.process is None or not self.process.is_alive() or self.connection is None:
            raise CanaryError("schema_validator_unavailable")
        try:
            self.connection.send((schema, value, check_only))
            if not self.connection.poll(self.timeout):
                self.process.terminate()
                self.process.join(timeout=1)
                raise CanaryError("schema_validation_deadline_exceeded")
            response = self.connection.recv()
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise CanaryError("schema_validator_unavailable") from exc
        if "error" in response:
            raise CanaryError(response["error"])
        return response["issues"]

    def __exit__(self, *_: Any) -> None:
        if self.process is not None:
            if self.process.is_alive() and self.connection is not None:
                try:
                    self.connection.send(None)
                except (BrokenPipeError, OSError):
                    pass
            self.process.join(timeout=0.5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=0.5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
        if self.connection is not None:
            self.connection.close()
