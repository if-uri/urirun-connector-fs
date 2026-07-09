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

import base64
import hashlib
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import _urirun_compat as urirun

CONNECTOR_ID = "fs"
FS = urirun.connector(CONNECTOR_ID, scheme="fs", target="host", meta={"label": "Filesystem duplicates"})

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


def _expand_path(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


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


@FS.handler("file/query/read-b64", isolated=True,
            meta={"label": "Read one file as base64", "cliAlias": "read-b64"})
def read_b64(path: str = "", max_bytes: int = 3_000_000) -> dict[str, Any]:
    """Read one file and return base64 bytes. Intended for small artifacts copied
    over a urirun node; use chunking/HTTP download for large files."""
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


@FS.handler("file/command/write-b64", isolated=True,
            meta={"label": "Write one base64 file", "cliAlias": "write-b64"})
def write_b64(path: str = "", bytes_b64: str = "", overwrite: bool = False,
              make_dirs: bool = True) -> dict[str, Any]:
    """Write one base64 payload to `path`. By default it never overwrites; if the
    target exists, a numbered suffix is added."""
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
    # REVERSIBILITY CONTRACT: snapshot the prior content (to the resolution of the file bytes)
    # BEFORE writing, so the return carries a concrete inverse — restore-previous when this write
    # replaced an existing file, otherwise delete the file this write created.
    prior_b64 = base64.b64encode(final.read_bytes()).decode("ascii") if final.exists() else None
    tmp = final.with_name(f".{final.name}.tmp-{os.getpid()}-{int(time.time() * 1000)}")
    tmp.write_bytes(data)
    tmp.replace(final)
    inverse = ({"uri": "fs://host/file/command/write-b64",
                "args": {"path": str(final), "bytes_b64": prior_b64, "overwrite": True}}
               if prior_b64 is not None
               else {"uri": "fs://host/file/command/delete", "args": {"path": str(final)}})
    return {"ok": True, "connector": CONNECTOR_ID, "path": str(final), "requestedPath": str(target),
            "overwritten": bool(overwrite and final == target), "renamed": final != target,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "inverse": inverse}


@FS.handler("archive/command/unpack-b64", isolated=True,
            meta={"label": "Extract a base64 tar.gz into a directory", "cliAlias": "unpack-b64"})
def unpack_b64(dest: str = "", bytes_b64: str = "", strip_components: int = 0) -> dict[str, Any]:
    """Extract a base64 tar.gz into ``dest`` (created if missing). One-shot DIRECTORY copy over
    the mesh: the host tars a folder, sends it as one base64 payload, the node unpacks it here —
    no per-file writes, no shell:// tar. Members are constrained to ``dest`` (path-traversal is
    rejected). Returns the written paths so the caller can verify the copy."""
    import io
    import tarfile
    if not dest:
        return {"ok": False, "error": "dest is required"}
    if not bytes_b64:
        return {"ok": False, "error": "bytes_b64 is required"}
    root = _expand_path(dest)
    try:
        data = base64.b64decode(bytes_b64.encode("ascii"), validate=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"invalid base64 payload: {exc}"}
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                parts = member.name.split("/")
                if strip_components:
                    parts = parts[strip_components:]
                rel = "/".join(p for p in parts if p and p != "..")
                if not rel:
                    continue
                target = (root / rel).resolve()
                if os.path.commonpath([str(target), str(root)]) != str(root):
                    return {"ok": False, "error": f"unsafe path in archive: {member.name}"}
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(member)
                if src is None:
                    continue
                target.write_bytes(src.read())
                written.append(str(target))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"unpack failed: {exc}"}
    return {"ok": True, "connector": CONNECTOR_ID, "dest": str(root),
            "files": written, "count": len(written)}


@FS.handler("file/command/delete", isolated=True,
            meta={"label": "Delete one file (reversible: inverse restores the bytes)", "cliAlias": "delete"})
def delete(path: str = "") -> dict[str, Any]:
    """Delete ``path``. Reversible per the engine contract: the bytes are snapshotted BEFORE
    removal so the returned ``inverse`` re-writes them — a delete that ran inside a flow can be
    rolled back. Missing file is a no-op failure (nothing to undo)."""
    if not path:
        return {"ok": False, "error": "path is required"}
    target = _expand_path(path)
    if not target.is_file():
        return {"ok": False, "error": f"not a file: {target}"}
    data = target.read_bytes()                       # snapshot before removal
    target.unlink()
    return {"ok": True, "connector": CONNECTOR_ID, "path": str(target), "bytes": len(data),
            "inverse": {"uri": "fs://host/file/command/write-b64",
                        "args": {"path": str(target),
                                 "bytes_b64": base64.b64encode(data).decode("ascii"),
                                 "overwrite": True}}}


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


def _find_perceptual(root: str, extensions, min_size: int, threshold: int) -> list | dict[str, Any]:
    items = []
    for p in _iter_files(root, extensions or list(_IMAGE_EXTS), min_size):
        if os.path.splitext(p)[1].lower() in _IMAGE_EXTS:
            ph = _phash(p)
            if ph:
                items.append((p, ph))
    if not items:
        return {"ok": False, "error": "no images fingerprinted (need pillow + imagehash/img2nl)",
                "connector": CONNECTOR_ID, "mode": "perceptual"}
    used: set[str] = set()
    groups: list[dict[str, Any]] = []
    for i, (pa, ha) in enumerate(items):
        if pa in used:
            continue
        cluster = [pa]
        for pb, hb in items[i + 1:]:
            if pb not in used:
                d = _hamming_hex(ha, hb)
                if d is not None and d <= threshold:
                    cluster.append(pb)
                    used.add(pb)
        if len(cluster) > 1:
            used.add(pa)
            groups.append({"key": ha, "count": len(cluster), "files": cluster})
    return groups


def _find_sha256(root: str, extensions, min_size: int) -> list[dict[str, Any]]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for p in _iter_files(root, extensions, min_size):
        h = _sha256(p)
        if h:
            by_hash[h].append(p)
    return [{"key": h, "count": len(paths), "files": sorted(paths)}
            for h, paths in by_hash.items() if len(paths) > 1]


def _reclaimable_bytes(groups: list[dict[str, Any]]) -> int:
    total = 0
    for g in groups:
        try:
            total += os.path.getsize(g["files"][0]) * (g["count"] - 1)
        except OSError:
            pass
    return total


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
    if mode == "perceptual":
        result = _find_perceptual(root, extensions, min_size, threshold)
        if isinstance(result, dict):
            return result
        groups = result
    else:
        groups = _find_sha256(root, extensions, min_size)
    groups.sort(key=lambda g: g["count"], reverse=True)
    return {"ok": True, "connector": CONNECTOR_ID, "root": root, "mode": mode,
            "threshold": threshold if mode == "perceptual" else None,
            "duplicateGroups": len(groups), "extraFiles": sum(g["count"] - 1 for g in groups),
            "reclaimableBytes": _reclaimable_bytes(groups), "groups": groups[:max_groups]}


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
