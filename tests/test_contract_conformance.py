# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""Conformance gate for the fs connector's route contracts.

Pure filesystem I/O → the gate runs the REAL handlers against a temp dir and asserts each live
envelope conforms to its contract, including the reversible write-b64/delete pair whose inverse.args
must satisfy the inverse route's input (verified statically by conform and at runtime here).
"""
from __future__ import annotations

import base64

import urirun_connector_fs.core as core
from urirun_connector_fs.contracts import CONTRACTS
from urirun_connectors_toolkit.contract_gate import conform, envelope_violation


def test_contracts_conform():
    conform(CONTRACTS)


def test_every_route_has_a_contract():
    live = set(core.urirun_bindings()["bindings"])
    contracted = set(CONTRACTS)
    assert not (contracted - live), f"contracts point at missing routes: {sorted(contracted - live)}"
    assert not (live - contracted), f"routes without a contract: {sorted(live - contracted)}"


def test_live_output_conforms_to_contract(tmp_path):
    """Run the real fs handlers against a temp dir and assert live output conforms."""
    b64 = base64.b64encode(b"hello world").decode()
    a = str(tmp_path / "a.txt")
    b = str(tmp_path / "b.txt")

    def conforms(uri, env):
        bad = envelope_violation(CONTRACTS[uri], env)
        assert bad is None, f"{uri}: live output violates contract: {bad}\nenvelope={env}"

    conforms("fs://host/file/command/write-b64", core.write_b64(path=a, bytes_b64=b64))
    conforms("fs://host/file/query/read-b64", core.read_b64(path=a))
    core.write_b64(path=b, bytes_b64=b64)  # a duplicate for dedup
    conforms("fs://host/duplicates/query/find", core.find(root=str(tmp_path), mode="sha256"))
    conforms("fs://host/duplicates/command/move", core.move(root=str(tmp_path), mode="sha256", dry_run=True))
    conforms("fs://host/file/command/delete", core.delete(path=a))
