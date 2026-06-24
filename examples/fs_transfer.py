# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
#
# Self-contained fs transfer handler for SIGNED /deploy to a urirun node that runs an
# OUTDATED urirun-connector-fs (missing file/command/write-b64 + file/query/read-b64) and
# has no --manage surface (so the host's ensure_scheme self-heal cannot install it).
#
# Provides exactly the two routes document-sync (document://host/archive/command/sync-to-node)
# requires, with the SAME return shape as urirun-connector-fs, so the document-sync.v1
# contract (write-ack + read-back-sha256) verifies. Stdlib only.
#
# IMPORTANT: the deployed module name is this file's basename minus .py, and the bindings
# reference `module: "fs_transfer"` — so this file MUST stay named fs_transfer.py.
#
# Deploy (no SSH, no --manage):
#   urirun host deploy <node> --code fs_transfer.py \
#       --bindings fs-transfer-bindings.json --identity ~/.ssh/id_ed25519 --allow 'fs://**' --merge
# In-memory on the node (reverts on its restart). Durable fix = update urirun-connector-fs there.

from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path
from typing import Any

CONNECTOR_ID = "fs"


def _expand_path(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def _unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for i in range(1, 10000):
        candidate = target.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    return target.with_name(f"{stem}-{int(time.time())}{suffix}")


def read_b64(path: str = "", max_bytes: int = 3_000_000, **_ignored: Any) -> dict[str, Any]:
    """Read one file as base64 + sha256 (the read-back half of the sync verification)."""
    source = _expand_path(path)
    if not source.is_file():
        return {"ok": False, "error": f"not a file: {source}"}
    size = source.stat().st_size
    if max_bytes > 0 and size > max_bytes:
        return {"ok": False, "error": f"file too large for read-b64: {size} > {max_bytes}",
                "path": str(source), "bytes": size}
    data = source.read_bytes()
    return {"ok": True, "connector": CONNECTOR_ID, "path": str(source), "name": source.name,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes_b64": base64.b64encode(data).decode("ascii")}


def write_b64(path: str = "", bytes_b64: str = "", overwrite: bool = False,
              make_dirs: bool = True, **_ignored: Any) -> dict[str, Any]:
    """Write one base64 payload to `path`, returning {ok, path, sha256, ...} for write-ack."""
    if not path:
        return {"ok": False, "error": "path is required"}
    if not bytes_b64:
        return {"ok": False, "error": "bytes_b64 is required"}
    target = _expand_path(path)
    if make_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.parent.is_dir():
        return {"ok": False, "error": f"directory does not exist: {target.parent}"}
    final = target if overwrite else _unique_path(target)
    try:
        data = base64.b64decode(bytes_b64.encode("ascii"), validate=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"invalid base64 payload: {exc}"}
    tmp = final.with_name(f".{final.name}.tmp-{os.getpid()}-{int(time.time() * 1000)}")
    tmp.write_bytes(data)
    tmp.replace(final)
    return {"ok": True, "connector": CONNECTOR_ID, "path": str(final), "requestedPath": str(target),
            "overwritten": bool(overwrite and final == target), "renamed": final != target,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
