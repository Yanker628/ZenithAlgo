from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def sha256_bytes(payload: bytes) -> str:
    h = hashlib.sha256()
    h.update(payload)
    return h.hexdigest()


def sha256_text(text: str, *, encoding: str = "utf-8") -> str:
    return sha256_bytes(text.encode(encoding))


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_files(paths: Iterable[str | Path]) -> tuple[str, dict[str, str]]:
    """
    计算一组文件的 hash，并返回一个稳定的聚合 hash：
    - per_file: {path_str: sha256}
    - combined: sha256( join(sorted(path=hash)) )
    """
    per_file: dict[str, str] = {}
    for p in paths:
        ps = str(p)
        per_file[ps] = sha256_file(p)
    combined_payload = "\n".join(f"{k}={per_file[k]}" for k in sorted(per_file.keys()))
    return sha256_text(combined_payload), per_file

