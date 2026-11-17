"""Download the official PlantSeg archive from Zenodo using byte ranges."""
from __future__ import annotations

import concurrent.futures
import hashlib
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://zenodo.org/records/17719108/files/plantseg.zip?download=1"
EXPECTED_SIZE = 1_057_281_724
EXPECTED_MD5 = "9358a66dff88cdd15c4fe009763c40a3"
ROOT = Path(__file__).parent
DATA = ROOT / "data"
PARTS = DATA / ".plantseg-parts"
ARCHIVE = DATA / "plantseg.zip"
CHUNK_SIZE = 32 * 1024 * 1024
WORKERS = 8


def fetch_range(index: int, start: int, end: int) -> Path:
    target = PARTS / f"part-{index:03d}.bin"
    expected_length = end - start + 1
    if target.is_file() and target.stat().st_size == expected_length:
        return target
    for attempt in range(1, 5):
        try:
            request = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}", "User-Agent": "KhetSaathi/1.0 dataset setup"})
            with urllib.request.urlopen(request, timeout=120) as response:
                content_range = response.headers.get("Content-Range", "")
                if response.status != 206 or not content_range.startswith(f"bytes {start}-{end}/"):
                    raise RuntimeError(f"Zenodo returned unexpected range response: {content_range or response.status}")
                with target.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
            if target.stat().st_size != expected_length:
                raise RuntimeError(f"Chunk {index} has an unexpected length")
            return target
        except (OSError, urllib.error.URLError, RuntimeError):
            target.unlink(missing_ok=True)
            if attempt == 4:
                raise
            time.sleep(attempt * 2)
    raise RuntimeError(f"Could not fetch chunk {index}")


def main():
    DATA.mkdir(exist_ok=True)
    if ARCHIVE.is_file() and ARCHIVE.stat().st_size == EXPECTED_SIZE:
        print(f"Found {ARCHIVE}; verifying checksum.")
    else:
        PARTS.mkdir(parents=True, exist_ok=True)
        chunks = [(index, start, min(start + CHUNK_SIZE, EXPECTED_SIZE) - 1)
                  for index, start in enumerate(range(0, EXPECTED_SIZE, CHUNK_SIZE))]
        print(f"Downloading PlantSeg ({EXPECTED_SIZE / (1024**3):.2f} GiB) in {len(chunks)} ranged chunks...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(fetch_range, *chunk) for chunk in chunks]
            for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                future.result()
                print(f"Downloaded {done}/{len(chunks)} chunks")
        temporary = DATA / "plantseg.zip.part"
        with temporary.open("wb") as output:
            for index, _, _ in chunks:
                with (PARTS / f"part-{index:03d}.bin").open("rb") as part:
                    shutil.copyfileobj(part, output)
        temporary.replace(ARCHIVE)
        shutil.rmtree(PARTS)

    digest = hashlib.md5()
    with ARCHIVE.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if ARCHIVE.stat().st_size != EXPECTED_SIZE or digest.hexdigest() != EXPECTED_MD5:
        raise RuntimeError("PlantSeg archive failed its size or Zenodo MD5 check; delete data/plantseg.zip and retry.")
    print(f"Verified {ARCHIVE} (Zenodo MD5 matches). Extract it into data/PlantSeg before training.")


if __name__ == "__main__":
    main()
