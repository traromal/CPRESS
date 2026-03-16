from pathlib import Path
import json
import os

def write_parity(path: Path, chunk_size: int = 2 * 1024 * 1024) -> Path:
    import hashlib
    meta = {
        "file": str(path),
        "size": path.stat().st_size,
        "chunk_size": chunk_size,
        "hash": "sha256",
        "chunks": [],
    }
    with path.open("rb") as f:
        idx = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h = hashlib.sha256(chunk).hexdigest()
            meta["chunks"].append({"index": idx, "sha256": h})
            idx += 1
    out = path.with_suffix(path.suffix + ".parity.json")
    out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out

def verify_parity(parity_file: Path) -> bool:
    import hashlib
    meta = json.loads(parity_file.read_text(encoding="utf-8"))
    archive_path = Path(meta["file"])
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive missing: {archive_path}")
    if archive_path.stat().st_size != meta.get("size"):
        raise ValueError("Size mismatch")
    chunk_size = int(meta.get("chunk_size", 2 * 1024 * 1024))
    with archive_path.open("rb") as f:
        for chunk_meta in meta.get("chunks", []):
            chunk = f.read(chunk_size)
            if not chunk:
                raise ValueError("Archive shorter than parity")
            if hashlib.sha256(chunk).hexdigest() != chunk_meta["sha256"]:
                raise ValueError(f"Chunk {chunk_meta['index']} hash mismatch")
    return True

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "write":
        write_parity(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify_parity(Path(sys.argv[2]))
