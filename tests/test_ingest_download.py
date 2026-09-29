"""Checksummed downloads: cache reuse, refresh, retries and failures."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from app.ingest.download import combined_checksum, download_file, sha256_of_file

PAYLOAD = b"ZCTA5CE20|ALAND20\n80123|31138889\n"


def _client(responses: list[int]) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        status = responses.pop(0)
        return httpx.Response(status, content=PAYLOAD if status == 200 else b"nope")

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_download_writes_file_and_sidecar_then_reuses_cache(tmp_path: Path) -> None:
    client, seen = _client([200])
    dest = tmp_path / "raw" / "file.txt"
    first = download_file("https://example.test/file.txt", dest, client=client)
    assert first.downloaded and first.path == dest and dest.read_bytes() == PAYLOAD
    assert first.sha256 == hashlib.sha256(PAYLOAD).hexdigest() == sha256_of_file(dest)
    assert (tmp_path / "raw" / "file.txt.sha256").read_text().split()[0] == first.sha256
    second = download_file("https://example.test/file.txt", dest, client=client)
    assert not second.downloaded and second.sha256 == first.sha256 and len(seen) == 1
    assert not list((tmp_path / "raw").glob("*.part"))


def test_refresh_redownloads_and_retries_transient_errors(tmp_path: Path) -> None:
    dest = tmp_path / "file.txt"
    dest.write_bytes(b"stale")
    client, seen = _client([503, 200])
    result = download_file(
        "https://example.test/file.txt", dest, client=client, refresh=True, backoff_seconds=0
    )
    assert result.downloaded and dest.read_bytes() == PAYLOAD and len(seen) == 2


def test_hard_failure_raises_and_leaves_no_partial_file(tmp_path: Path) -> None:
    client, _ = _client([404])
    with pytest.raises(httpx.HTTPStatusError):
        download_file("https://example.test/missing", tmp_path / "missing", client=client)
    assert not (tmp_path / "missing").exists() and not (tmp_path / "missing.part").exists()


def test_combined_checksum_is_order_independent() -> None:
    assert combined_checksum(["b", "a"]) == combined_checksum(["a", "b"])
    assert combined_checksum(["a"]) != combined_checksum(["b"])
