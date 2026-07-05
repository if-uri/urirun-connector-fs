# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""Route contracts for the fs connector (LLM-editable declaration).

fs is pure filesystem I/O → the gate runs the REAL handlers against a temp dir and asserts live
output conforms. Two commands are REVERSIBLE and return a concrete ``inverse`` (cross-route):
delete's inverse is write-b64 (re-write the snapshotted bytes), and a NEW write-b64's inverse is
delete. The conformance gate's inverse-args check verifies each example's ``inverse.args`` satisfy
the INPUT schema of the inverse route — so a broken rollback fails declaratively in CI.

Single scheme (fs) but routes are declared with mixed local/full paths; contract keys are FULL URIs
joined via ``attach_contracts(None, CONTRACTS)``.
"""
from __future__ import annotations

from urirun_connectors_toolkit.contract_gate import Contract

_W = "fs://host/file/command/write-b64"
_D = "fs://host/file/command/delete"

CONTRACTS: dict[str, Contract] = {

    "fs://host/file/query/read-b64": Contract(
        version="v1", effect="query",
        inp={"path": "str", "max_bytes": "?int"},
        out={"ok": "const:true", "connector": "const:fs", "path": "str", "name": "str",
             "bytes": "int", "sha256": "str", "bytes_b64": "str"},
        examples=(
            {"payload": {"path": "/tmp/a.txt"},
             "result": {"ok": True, "connector": "fs", "path": "/tmp/a.txt", "name": "a.txt",
                        "bytes": 11, "sha256": "b94d27b9...", "bytes_b64": "aGVsbG8gd29ybGQ="}},
        )),

    _W: Contract(
        version="v1", effect="command", reversible=True, inverse_route=_D,
        inp={"path": "str", "bytes_b64": "str", "overwrite": "?bool", "make_dirs": "?bool"},
        out={"ok": "const:true", "connector": "const:fs", "path": "str", "requestedPath": "str",
             "overwritten": "bool", "renamed": "bool", "bytes": "int", "sha256": "str",
             "inverse": {"uri": "str", "args": "obj"}},
        # NEW-file write → inverse is delete. (A REPLACE write returns inverse=write-b64 with the
        # prior bytes; that variant is exercised at runtime, not declared as the static inverse.)
        examples=(
            {"payload": {"path": "/tmp/a.txt", "bytes_b64": "aGVsbG8gd29ybGQ="},
             "result": {"ok": True, "connector": "fs", "path": "/tmp/a.txt", "requestedPath": "/tmp/a.txt",
                        "overwritten": False, "renamed": False, "bytes": 11, "sha256": "b94d27b9...",
                        "inverse": {"uri": _D, "args": {"path": "/tmp/a.txt"}}}},
        )),

    _D: Contract(
        version="v1", effect="command", reversible=True, inverse_route=_W,
        inp={"path": "str"},
        out={"ok": "const:true", "connector": "const:fs", "path": "str", "bytes": "int",
             "inverse": {"uri": "str", "args": "obj"}},
        examples=(
            {"payload": {"path": "/tmp/a.txt"},
             "result": {"ok": True, "connector": "fs", "path": "/tmp/a.txt", "bytes": 11,
                        "inverse": {"uri": _W, "args": {"path": "/tmp/a.txt",
                                                        "bytes_b64": "aGVsbG8gd29ybGQ=", "overwrite": True}}}},
        )),

    # One-shot base64 tar.gz → directory extract (path-traversal constrained). Not declared
    # reversible: undo would require deleting exactly the members written, which we don't snapshot.
    "fs://host/archive/command/unpack-b64": Contract(
        version="v1", effect="command", reversible=False,
        inp={"dest": "str", "bytes_b64": "str", "strip_components": "?int"},
        out={"ok": "const:true", "connector": "const:fs", "dest": "str",
             "files": "list", "count": "int"},
        examples=(
            {"payload": {"dest": "/tmp/out", "bytes_b64": "H4sIAAAA..."},
             "result": {"ok": True, "connector": "fs", "dest": "/tmp/out",
                        "files": ["/tmp/out/a.txt"], "count": 1}},
        )),

    "fs://host/duplicates/query/find": Contract(
        version="v1", effect="query",
        inp={"root": "str", "extensions": "?list", "min_size": "?int", "mode": "?str",
             "threshold": "?int", "max_groups": "?int"},
        out={"ok": "const:true", "connector": "const:fs", "root": "str", "mode": "str",
             "duplicateGroups": "int", "extraFiles": "int", "reclaimableBytes": "int", "groups": "list"},
        examples=(
            {"payload": {"root": "/tmp", "mode": "sha256"},
             "result": {"ok": True, "connector": "fs", "root": "/tmp", "mode": "sha256",
                        "threshold": None, "duplicateGroups": 1, "extraFiles": 1, "reclaimableBytes": 11,
                        "groups": [{"key": "b94d27b9...", "count": 2, "files": ["/tmp/a.txt", "/tmp/b.txt"]}]}},
        )),

    "fs://host/duplicates/command/move": Contract(
        version="v1", effect="command",
        inp={"root": "str", "extensions": "?list", "min_size": "?int", "mode": "?str",
             "threshold": "?int", "dry_run": "?bool"},
        out={"ok": "const:true", "connector": "const:fs", "root": "str", "mode": "str",
             "dryRun": "bool", "movedCount": "int", "moved": "list"},
        examples=(
            {"payload": {"root": "/tmp", "mode": "sha256", "dry_run": True},
             "result": {"ok": True, "connector": "fs", "root": "/tmp", "mode": "sha256", "dryRun": True,
                        "movedCount": 1, "moved": [{"from": "/tmp/b.txt", "to": "/tmp/_duplicates/x/b.txt",
                                                    "key": "b94d27b9..."}]}},
        )),
}
