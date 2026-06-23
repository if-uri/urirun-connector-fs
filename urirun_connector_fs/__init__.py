"""fs:// connector — URI duplicate-file detection (sha256) and near-duplicate images (perceptual)."""
from .core import FS, find, move, main, urirun_bindings

__all__ = ["FS", "find", "move", "main", "urirun_bindings"]
