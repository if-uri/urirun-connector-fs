#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

from urirun_llm_runtime import Executor


FS_FIND_URI = "fs://host/duplicates/query/find"
FORBIDDEN_PREFIXES = (
    "kvm://",
    "browser://",
    "http-check://",
    "router://",
    "mqtt://",
    "github://",
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _route_value(response: dict) -> dict:
    result = response.get("result")
    value = result.get("value", result) if isinstance(result, dict) else result
    if not isinstance(value, dict):
        fail(f"Response does not contain a dict result value: {response!r}")
    return value


def main() -> None:
    node_url = os.environ.get("URIRUN_NODE_URL", "http://127.0.0.1:18765")
    smoke_root = os.environ.get("FS_SMOKE_ROOT")
    if not smoke_root:
        fail("FS_SMOKE_ROOT is required")

    executor = Executor(node_url)

    health = executor.health()
    if not isinstance(health, dict):
        fail(f"/health returned non-dict response: {health!r}")

    routes = executor.routes()
    if FS_FIND_URI not in routes:
        fail(f"{FS_FIND_URI} is missing from /routes. Routes: {routes!r}")

    unexpected = [route for route in routes if route.startswith(FORBIDDEN_PREFIXES)]
    if unexpected:
        fail(f"Unexpected non-FS connector routes found: {unexpected!r}")

    response = executor.execute(
        FS_FIND_URI,
        {"root": smoke_root, "mode": "sha256", "min_size": 1},
    )
    if not isinstance(response, dict):
        fail(f"Executor returned non-dict response: {response!r}")
    if response.get("ok") is not True:
        fail(f"Executor returned failed response: {response!r}")

    value = _route_value(response)
    if value.get("ok") is not True:
        fail(f"FS duplicate route returned failed response: {response!r}")
    if value.get("connector") != "fs":
        fail(f"FS duplicate route returned wrong connector: {response!r}")
    if value.get("duplicateGroups", 0) < 1:
        fail(f"FS duplicate route did not find duplicate groups: {response!r}")

    print("OK: urirun-llm-runtime -> urirun node -> FS connector smoke test passed")


if __name__ == "__main__":
    main()
