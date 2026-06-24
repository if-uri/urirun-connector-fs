# urirun-connector-fs

**Filesystem duplicates** — connector ekosystemu [ifURI / urirun](https://github.com/if-uri/urirun).
Schemat URI: `fs://`

Find duplicate files in any folder over fs:// URIs. Exact byte duplicates by SHA-256 (stdlib) and near-duplicate IMAGES by perceptual hash (reusing wronai-img2nl analyze_fingerprint). A move command quarantines extras into _duplicates/, keeping the first of each group. Small files can also be copied through URI with `file/query/read-b64` and `file/command/write-b64`.

## Opis

fs:// turns duplicate detection and small artifact transfer into first-class URIs instead of ad-hoc shell + sha256sum/scp. fs://host/duplicates/query/find scans a folder tree and returns groups of duplicate files: mode=sha256 finds byte-identical files of any type; mode=perceptual finds near-duplicate images by perceptual hash (phash/dhash/whash via the wronai/img2nl fingerprint engine, compared by Hamming distance within a threshold). fs://host/duplicates/command/move quarantines the extra copies (all but the first of each group) into <root>/_duplicates/<key>/, with a dry_run default. fs://host/file/query/read-b64 and fs://host/file/command/write-b64 copy small files such as scanner PDFs between host and node without SSH. Built for the office flow — dedupe exported invoices and attachments.

## Transfer pliku do node

`write-b64` zapisuje małe artefakty, np. zeskanowane PDF-y, do wskazanej ścieżki. Domyślnie nie nadpisuje istniejących plików:

```json
{
  "uri": "fs://laptop/file/command/write-b64",
  "payload": {
    "path": "~/Downloads/2026-06/scan.pdf",
    "bytes_b64": "JVBERi0xLjQK...",
    "overwrite": false
  }
}
```

## Wymagania

- **python:** urirun
- **optional:** pillow + imagehash (or img2nl) for perceptual image mode

## Instalacja (dev)

```bash
pip install -e .
pytest -q
```

## Powiązane

- Rdzeń: [if-uri/urirun](https://github.com/if-uri/urirun)
- Hub connectorów: [connect.ifuri.com](https://connect.ifuri.com)

---
Kategoria: Filesystem · Słowa kluczowe: duplicates, dedupe, sha256, perceptual-hash, phash, imagehash, filesystem, invoice · Wydawca: if-uri
