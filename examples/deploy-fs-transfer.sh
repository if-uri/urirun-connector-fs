#!/usr/bin/env bash
# Deploy the fs transfer routes (file/command/write-b64 + file/query/read-b64) to a urirun
# node WITHOUT SSH and WITHOUT --manage, via a signed /deploy (uses your enrolled ed25519 key).
# Unblocks document://host/archive/command/sync-to-node when the node runs an outdated
# urirun-connector-fs that lacks these routes (the document-sync.v1 contract requires both).
#
# Usage:  ./deploy-fs-transfer.sh <node> [identity]
#   e.g.  ./deploy-fs-transfer.sh lenovo ~/.ssh/id_ed25519
#
# --merge ADDS the two routes without wiping the node's other routes. If the node runs a urirun
# old enough to still have the sibling "Route conflict: fs.file.query" merge bug, either update
# its urirun first, or drop --merge (which REPLACES the node registry — wipes its other routes
# until restart). Deploy is in-memory; it reverts on the node's restart. Durable fix: update
# urirun-connector-fs on the node (it already ships both routes).
set -euo pipefail

NODE="${1:?usage: deploy-fs-transfer.sh <node> [identity]}"
IDENTITY="${2:-$HOME/.ssh/id_ed25519}"
HOST_BIN="${HOST_BIN:-$HOME/.urirun-host/.venv/bin/urirun}"
DIR="$(cd "$(dirname "$0")" && pwd)"

"$HOST_BIN" host deploy "$NODE" \
  --code "$DIR/fs_transfer.py" \
  --bindings "$DIR/fs-transfer-bindings.json" \
  --identity "$IDENTITY" \
  --allow 'fs://**' \
  --merge

echo
echo "deployed fs write-b64 + read-b64 to '$NODE' (in-memory; reverts on node restart)."
echo "now retry the sync:  document://host/archive/command/sync-to-node  (node: $NODE)"
