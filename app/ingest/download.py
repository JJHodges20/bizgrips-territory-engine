"""Download a public file to data/raw with a recorded sha256 checksum.

A file that is already present is reused (its checksum is recomputed and the sidecar
``<name>.sha256`` refreshed) unless ``refresh=True``. Downloads are streamed to a temporary
``.part`` file and renamed on success, so an interrupted download never leaves a truncated
file in place.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

CHUNK_SIZE = 1 << 20
DEFAULT_TIMEOUT = httpx.Timeout(60.0, read=600.0)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size_bytes: int
    downloaded: bool  # False when an existing file was reused

    @property
    def status(self) -> str:
        return "downloaded" if self.downloaded else "cached"


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combined_checksum(digests: list[str]) -> str:
    """One sha256 over several per-file digests (order-independent) for multi-file sources."""
    return hashlib.sha256("\n".join(sorted(digests)).encode("ascii")).hexdigest()


def download_file(
    url: str,
    dest: Path,
    *,
    refresh: bool = False,
    client: httpx.Client | None = None,
    retries: int = 3,
    backoff_seconds: float = 2.0,
) -> DownloadResult:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        digest = sha256_of_file(dest)
        _write_sidecar(dest, digest)
        return DownloadResult(dest, digest, dest.stat().st_size, downloaded=False)

    owns_client = client is None
    client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    part = dest.with_name(dest.name + ".part")
    try:
        attempt = 0
        while True:
            attempt += 1
            try:
                digest = _stream_to(client, url, part)
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or (
                    exc.response.status_code in RETRY_STATUSES
                )
                if not retryable or attempt > retries:
                    part.unlink(missing_ok=True)
                    raise
                time.sleep(backoff_seconds * attempt)
        part.replace(dest)
    finally:
        if owns_client:
            client.close()
    _write_sidecar(dest, digest)
    return DownloadResult(dest, digest, dest.stat().st_size, downloaded=True)


def _stream_to(client: httpx.Client, url: str, part: Path) -> str:
    digest = hashlib.sha256()
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in response.iter_bytes(CHUNK_SIZE):
                fh.write(chunk)
                digest.update(chunk)
    return digest.hexdigest()


def _write_sidecar(dest: Path, digest: str) -> None:
    dest.with_name(dest.name + ".sha256").write_text(f"{digest}  {dest.name}\n", encoding="ascii")
