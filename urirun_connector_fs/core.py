# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
#
# fs:// connector — first-class URI duplicate detection over a folder tree, so finding
# duplicate files no longer needs shell:// + sha256sum by hand. Two modes: exact byte
# duplicates by SHA-256 (stdlib, always works) and near-duplicate IMAGES by perceptual
# hash (reusing wronai/img2nl's analyze_fingerprint — phash/dhash/whash + Hamming
# distance). A move command quarantines extras into a _duplicates/ folder, keeping the
# first of each group. Built for the office flow: dedupe exported invoices/attachments.

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from typing import Any

import urirun

CONNECTOR_ID = "fs"
FS = urirun.connector(CONNECTOR_ID, scheme="fs", target="host", meta={"label": "Filesystem duplicates"})

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


def _iter_files(root: str, extensions, min_size: int):
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in (extensions or [])}
    for dirpath, _dirs, files in os.walk(root):
        if os.path.basename(dirpath) == "_duplicates":
            continue  # never re-scan the quarantine folder
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                if not os.path.isfile(p) or os.path.getsize(p) < min_size:
                    continue
            except OSError:
                continue
            if exts and os.path.splitext(fn)[1].lower() not in exts:
                continue
            yield p


def _sha256(path: str, chunk: int = 1 << 20) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(chunk), b""):
                h.update(blk)
    except OSError:
        return None
    return h.hexdigest()


def _phash(path: str) -> str | None:
    """Perceptual hash, reusing wronai/img2nl's analyze_fingerprint; falls back to the
    imagehash library directly. Returns the phash hex, or None if unavailable."""
    try:
        from PIL import Image
        try:
            from img2nl.features.fingerprint import analyze_fingerprint  # type: ignore
            fp = analyze_fingerprint(Image.open(path))
            if fp.get("available"):
                return fp.get("phash")
        except Exception:  # noqa: BLE001
            import imagehash  # type: ignore
            return str(imagehash.phash(Image.open(path).convert("RGB")))
    except Exception:  # noqa: BLE001
        return None
    return None


def _hamming_hex(a: str, b: str) -> int | None:
    try:
        import imagehash  # type: ignore
        return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)
    except Exception:  # noqa: BLE001
        if len(a) != len(b):
            return None
        return bin(int(a, 16) ^ int(b, 16)).count("1")  # raw hex hamming fallback


@FS.handler("duplicates/query/find", isolated=True,
            meta={"label": "Find duplicate files in a folder (sha256 or perceptual image)", "cliAlias": "find"})
def find(root: str = "", extensions=None, min_size: int = 1, mode: str = "sha256",
         threshold: int = 5, max_groups: int = 1000) -> dict[str, Any]:
    """Find duplicate groups under `root`. mode=sha256 → exact byte-identical files (any type);
    mode=perceptual → near-duplicate images by perceptual hash within Hamming `threshold`.
    `extensions` (e.g. ['.pdf','.jpg']) and `min_size` (bytes) narrow the scan. Returns groups
    of 2+ files (first is the keeper), counts, and reclaimable bytes."""
    root = os.path.expanduser(root)
    if not root or not os.path.isdir(root):
        return {"ok": False, "error": f"not a directory: {root}"}
    groups = []
    if mode == "perceptual":
        items = []  # (path, phash)
        for p in _iter_files(root, extensions or list(_IMAGE_EXTS), min_size):
            if os.path.splitext(p)[1].lower() in _IMAGE_EXTS:
                ph = _phash(p)
                if ph:
                    items.append((p, ph))
        if not items:
            return {"ok": False, "error": "no images fingerprinted (need pillow + imagehash/img2nl)",
                    "connector": CONNECTOR_ID, "mode": mode}
        used = set()
        for i, (pa, ha) in enumerate(items):
            if pa in used:
                continue
            cluster = [pa]
            for pb, hb in items[i + 1:]:
                if pb in used:
                    continue
                d = _hamming_hex(ha, hb)
                if d is not None and d <= threshold:
                    cluster.append(pb); used.add(pb)
            if len(cluster) > 1:
                used.add(pa)
                groups.append({"key": ha, "count": len(cluster), "files": cluster})
    else:  # sha256
        by_hash: dict[str, list[str]] = defaultdict(list)
        for p in _iter_files(root, extensions, min_size):
            h = _sha256(p)
            if h:
                by_hash[h].append(p)
        for h, paths in by_hash.items():
            if len(paths) > 1:
                groups.append({"key": h, "count": len(paths), "files": sorted(paths)})
    groups.sort(key=lambda g: g["count"], reverse=True)
    reclaim = 0
    for g in groups:
        try:
            reclaim += os.path.getsize(g["files"][0]) * (g["count"] - 1)
        except OSError:
            pass
    return {"ok": True, "connector": CONNECTOR_ID, "root": root, "mode": mode,
            "threshold": threshold if mode == "perceptual" else None,
            "duplicateGroups": len(groups), "extraFiles": sum(g["count"] - 1 for g in groups),
            "reclaimableBytes": reclaim, "groups": groups[:max_groups]}


@FS.handler("duplicates/command/move", isolated=True,
            meta={"label": "Quarantine duplicate extras into _duplicates/ (keep first)", "cliAlias": "move"})
def move(root: str = "", extensions=None, min_size: int = 1, mode: str = "sha256",
         threshold: int = 5, dry_run: bool = True) -> dict[str, Any]:
    """Re-find duplicates and MOVE every extra (all but the first of each group) into
    <root>/_duplicates/<key-prefix>/. dry_run=True (default) only reports what would move."""
    res = find(root=root, extensions=extensions, min_size=min_size, mode=mode, threshold=threshold)
    if not res.get("ok"):
        return res
    root = res["root"]
    moved = []
    for g in res["groups"]:
        dest = os.path.join(root, "_duplicates", str(g["key"])[:12])
        for src in g["files"][1:]:
            base = os.path.basename(src)
            target = os.path.join(dest, base)
            rec = {"from": src, "to": target, "key": g["key"]}
            if not dry_run:
                os.makedirs(dest, exist_ok=True)
                n, stem_ext = 1, os.path.splitext(base)
                while os.path.exists(target):
                    target = os.path.join(dest, f"{stem_ext[0]}_{n}{stem_ext[1]}"); n += 1
                    rec["to"] = target
                os.rename(src, target)
            moved.append(rec)
    return {"ok": True, "connector": CONNECTOR_ID, "root": root, "mode": mode, "dryRun": dry_run,
            "movedCount": len(moved), "moved": moved[:500]}


def main(argv: list[str] | None = None) -> int:
    return FS.cli(argv, manifest_prose=urirun.load_manifest(__package__))


urirun_bindings = FS.bindings
