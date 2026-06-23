"""Offline tests for the fs connector: sha256 dedup, perceptual (optional), move."""
import os
import pytest
import urirun_connector_fs.core as c


def test_bindings_valid():
    b = c.urirun_bindings()
    assert set(b["bindings"]) == {"fs://host/duplicates/query/find", "fs://host/duplicates/command/move"}


def test_sha256_finds_exact_duplicates(tmp_path):
    (tmp_path / "a.txt").write_text("INVOICE-123")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a_copy.txt").write_text("INVOICE-123")   # identical
    (tmp_path / "other.txt").write_text("DIFFERENT")
    r = c.find(root=str(tmp_path), mode="sha256")
    assert r["ok"] and r["duplicateGroups"] == 1
    assert r["extraFiles"] == 1
    grp = r["groups"][0]
    assert grp["count"] == 2
    assert {os.path.basename(p) for p in grp["files"]} == {"a.txt", "a_copy.txt"}


def test_extensions_and_minsize_filter(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x" * 2000)
    (tmp_path / "b.pdf").write_bytes(b"x" * 2000)   # dup
    (tmp_path / "c.txt").write_bytes(b"x" * 2000)   # filtered out by extension
    (tmp_path / "tiny.pdf").write_bytes(b"x")        # filtered out by min_size
    r = c.find(root=str(tmp_path), mode="sha256", extensions=[".pdf"], min_size=100)
    assert r["duplicateGroups"] == 1 and r["groups"][0]["count"] == 2


def test_reclaimable_bytes(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"y" * 500)
    (tmp_path / "b.bin").write_bytes(b"y" * 500)
    (tmp_path / "d.bin").write_bytes(b"y" * 500)     # 3 copies → reclaim 2*500
    r = c.find(root=str(tmp_path), mode="sha256")
    assert r["reclaimableBytes"] == 1000


def test_move_dry_run_does_not_touch_files(tmp_path):
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    r = c.move(root=str(tmp_path), mode="sha256", dry_run=True)
    assert r["ok"] and r["movedCount"] == 1
    assert (tmp_path / "b.txt").exists()             # nothing moved on a dry run
    assert not (tmp_path / "_duplicates").exists()


def test_move_quarantines_extras(tmp_path):
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    r = c.move(root=str(tmp_path), mode="sha256", dry_run=False)
    assert r["movedCount"] == 1
    assert (tmp_path / "a.txt").exists()             # keeper stays
    assert (tmp_path / "_duplicates").exists()       # extra quarantined


def test_perceptual_mode_needs_images_or_reports_cleanly(tmp_path):
    pytest.importorskip("PIL")
    pytest.importorskip("imagehash")
    from PIL import Image
    img = Image.new("RGB", (64, 64), "white")
    img.save(tmp_path / "x.png")
    img.save(tmp_path / "x_copy.png")
    r = c.find(root=str(tmp_path), mode="perceptual", threshold=5)
    assert r["ok"] and r["duplicateGroups"] == 1
