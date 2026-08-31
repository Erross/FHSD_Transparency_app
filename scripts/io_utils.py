"""Deterministic JSON/gzip helpers used by archive tooling."""
from __future__ import annotations
import gzip, json
from pathlib import Path
from typing import Any

def read_json(path: Path) -> Any:
    raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    return json.loads(raw.decode('utf-8'))

def write_json_gz(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    path.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))

def write_raw_gz(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
