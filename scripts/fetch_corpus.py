#!/usr/bin/env python3
"""Fetch overset's starter corpus: 63 native .pptx decks with stated open licences.

    uv run --group corpus scripts/fetch_corpus.py            # fetch, or verify what is there
    uv run --group corpus scripts/fetch_corpus.py --reselect # pick the sample again from the sources

The sample, from three Hugging Face datasets (see docs/corpus.md for why these):

- Zenodo10K (Forceless/Zenodo10K): 42 decks licensed CC-BY-4.0 or CC0, six from each
  year 2018-2024. Real conference and project decks: many masters, pasted images, odd fonts.
- Slides-Align (Yqy6/Slides-Align, MIT): three decks from each of six AI slide products,
  chosen among the products with at least three .pptx decks. AI decks break in ways people's
  decks rarely do.
- Datacluster multi-domain PowerPoint (CC-BY-4.0): the three smallest decks.

Every deck is at most 8 MB. Choices use a fixed seed, so a reselect picks the same files while
the sources are unchanged. The choice is recorded in data/manifest.csv -- file, source, licence,
title, DOI, URL, slide count, bytes, SHA-256 -- and a later run only downloads what is missing or
fails its checksum, so a second run is a no-op. The decks themselves are never committed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
import re
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HF = "https://huggingface.co"
SEED = 19
MAX_BYTES = 8 * 2**20
TIMEOUT = 60

ZENODO = "Forceless/Zenodo10K"
ZENODO_LICENCES = ("cc-by-4.0", "cc-zero")
ZENODO_YEARS = range(2018, 2025)
ZENODO_PER_YEAR = 6
SLIDES_ALIGN = "Yqy6/Slides-Align"
SLIDES_ALIGN_PRODUCTS, SLIDES_ALIGN_PER_PRODUCT = 6, 3
DATACLUSTER = "Dataclusterlabspvtltd/multi-domain-powerpoint-presentation-dataset"
DATACLUSTER_COUNT = 3


@dataclass
class Deck:
    file: str  # path under the data directory's pptx/ folder
    source: str
    licence: str
    title: str
    doi: str
    url: str
    slides: int
    bytes: int
    sha256: str


@dataclass
class Remote:
    """A file in a Hugging Face dataset, as its tree API lists it."""

    dataset: str
    path: str
    size: int
    sha256: str  # the LFS object id

    @property
    def url(self) -> str:
        return f"{HF}/datasets/{self.dataset}/resolve/main/{urllib.parse.quote(self.path)}"


# --- Hugging Face -------------------------------------------------------------------------------


def get(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "overset-corpus"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read(), response.headers.get("Link", "")


def tree(dataset: str, path: str = "", recursive: bool = False) -> list[Remote]:
    """Every file under `path`, following the API's pages."""
    import json

    query = "?recursive=true&limit=1000" if recursive else "?limit=1000"
    url = f"{HF}/api/datasets/{dataset}/tree/main/{urllib.parse.quote(path)}{query}"
    out = []
    while url:
        body, link = get(url)
        for item in json.loads(body):
            if item.get("type") == "file":
                sha = (item.get("lfs") or {}).get("oid", "")
                out.append(Remote(dataset, item["path"], int(item["size"]), sha))
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = match.group(1) if match else ""
    return out


def _pptx(files: list[Remote]) -> list[Remote]:
    return sorted((f for f in files if f.path.lower().endswith(".pptx") and f.size <= MAX_BYTES), key=lambda f: f.path)


# --- choosing the sample ------------------------------------------------------------------------


def choose_zenodo(by_year: dict[int, list[Remote]], rng: random.Random) -> list[Remote]:
    out = []
    for year in ZENODO_YEARS:
        pool = _pptx(by_year.get(year, []))
        if len(pool) < ZENODO_PER_YEAR:
            raise SystemExit(f"Zenodo10K {year}: only {len(pool)} eligible decks")
        out += rng.sample(pool, ZENODO_PER_YEAR)
    return out


def choose_slides_align(by_product: dict[str, list[Remote]], rng: random.Random) -> list[Remote]:
    pools = {p: _pptx(files) for p, files in sorted(by_product.items())}
    eligible = [p for p, pool in pools.items() if len(pool) >= SLIDES_ALIGN_PER_PRODUCT]
    if len(eligible) < SLIDES_ALIGN_PRODUCTS:
        raise SystemExit(f"Slides-Align: only {len(eligible)} products with enough .pptx decks")
    out = []
    for product in sorted(rng.sample(eligible, SLIDES_ALIGN_PRODUCTS)):
        out += rng.sample(pools[product], SLIDES_ALIGN_PER_PRODUCT)
    return out


def choose_datacluster(files: list[Remote]) -> list[Remote]:
    return sorted(_pptx(files), key=lambda f: (f.size, f.path))[:DATACLUSTER_COUNT]


def zenodo_metadata() -> dict[str, dict]:
    """The dataset's metadata (title, DOI, licence), keyed by each file's MD5 -- which is also the
    prefix of its name in the dataset."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("Reading Zenodo10K's metadata needs pyarrow: run with `uv run --group corpus ...`") from None
    body, _ = get(f"{HF}/datasets/{ZENODO}/resolve/main/data/pptx-00000-of-00001.parquet")
    with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
        tmp.write(body)
        tmp.flush()
        rows = pq.read_table(tmp.name).to_pylist()
    return {row["checksum"].removeprefix("md5:"): row for row in rows}


def select() -> list[tuple[Remote, str, str, str, str, str]]:
    """The sample: (remote, local file, source, licence, title, DOI) per deck."""
    picks = []

    print("Listing Zenodo10K ...", file=sys.stderr)
    by_year: dict[int, list[Remote]] = {}
    for licence in ZENODO_LICENCES:
        for year in ZENODO_YEARS:
            by_year.setdefault(year, []).extend(tree(ZENODO, f"pptx/{licence}/{year}"))
    meta = zenodo_metadata()
    for f in choose_zenodo(by_year, random.Random(f"{SEED}-zenodo")):
        name = f.path.rsplit("/", 1)[-1]
        row = meta.get(name.split("-", 1)[0], {})
        licence = f.path.split("/")[1]
        picks.append((f, f"zenodo10k/{name}", "Zenodo10K", licence, row.get("title", ""), row.get("doi", "")))

    print("Listing Slides-Align ...", file=sys.stderr)
    products = _directories(SLIDES_ALIGN)
    by_product = {p: tree(SLIDES_ALIGN, p, recursive=True) for p in products}
    for f in choose_slides_align(by_product, random.Random(f"{SEED}-slides-align")):
        product, _, topic = f.path.split("/")[:3]
        local = f"slides-align/{product}/{topic}.pptx"
        picks.append((f, local, "Slides-Align", "mit", f"{product}: {topic}", ""))

    print("Listing Datacluster ...", file=sys.stderr)
    for f in choose_datacluster(tree(DATACLUSTER, recursive=True)):
        name = f.path.rsplit("/", 1)[-1]
        picks.append((f, f"datacluster/{name}", "Datacluster", "cc-by-4.0", name.removesuffix(".pptx"), ""))
    return picks


def _directories(dataset: str) -> list[str]:
    import json

    body, _ = get(f"{HF}/api/datasets/{dataset}/tree/main")
    return sorted(item["path"] for item in json.loads(body) if item.get("type") == "directory")


# --- downloading and recording ------------------------------------------------------------------


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(2**20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expected_sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "overset-corpus"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, partial.open("wb") as out:
        while chunk := response.read(2**20):
            out.write(chunk)
    got = sha256(partial)
    if expected_sha256 and got != expected_sha256:
        partial.unlink()
        raise SystemExit(f"{url}: SHA-256 {got} does not match the expected {expected_sha256}")
    partial.replace(dest)


def slide_count(path: Path) -> int:
    with zipfile.ZipFile(path) as z:
        return sum(1 for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))


def read_manifest(path: Path) -> list[Deck]:
    with path.open(newline="", encoding="utf-8") as f:
        return [Deck(**{**row, "slides": int(row["slides"]), "bytes": int(row["bytes"])}) for row in csv.DictReader(f)]


def write_manifest(path: Path, decks: list[Deck]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[x.name for x in fields(Deck)], lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(d) for d in sorted(decks, key=lambda d: d.file))


def ensure(data: Path, deck: Deck) -> bool:
    """Download the deck unless it is already there with the right checksum. True if downloaded."""
    dest = data / "pptx" / deck.file
    if dest.exists() and (not deck.sha256 or sha256(dest) == deck.sha256):
        return False  # no checksum yet: a just-listed small file, recorded once it is on disk
    print(f"  fetching {deck.file}", file=sys.stderr)
    download(deck.url, dest, deck.sha256)
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--data", type=Path, default=ROOT / "data", help="where the manifest and decks go (default: data/)")
    p.add_argument("--reselect", action="store_true", help="choose the sample again from the sources")
    args = p.parse_args(argv)
    manifest = args.data / "manifest.csv"

    if manifest.exists() and not args.reselect:
        decks = read_manifest(manifest)
        fetched = sum(ensure(args.data, d) for d in decks)
    else:
        decks, fetched = [], 0
        for remote, local, source, licence, title, doi in select():
            deck = Deck(local, source, licence, title, doi, remote.url, 0, remote.size, remote.sha256)
            fetched += ensure(args.data, deck)
            path = args.data / "pptx" / local
            deck.slides = slide_count(path)
            # Small files are stored in git, not LFS, so the listing gives no SHA-256: record the
            # downloaded file's, so later runs can verify it.
            deck.sha256 = deck.sha256 or sha256(path)
            decks.append(deck)
        args.data.mkdir(parents=True, exist_ok=True)
        write_manifest(manifest, decks)

    total = sum(d.bytes for d in decks)
    print(f"{len(decks)} decks, {total / 2**20:.0f} MB in {args.data / 'pptx'}; downloaded {fetched}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
