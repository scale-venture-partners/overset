"""scripts/fetch_corpus.py and scripts/run_corpus.py, without the network: the sampling rules on
made-up listings, the manifest's no-op second run, and the summary table."""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_corpus as fc  # noqa: E402
import run_corpus as rc  # noqa: E402

MB = 2**20


def remote(path, size=MB, dataset="d"):
    return fc.Remote(dataset, path, size, "")


def test_zenodo_takes_six_decks_from_each_year_under_the_cap():
    by_year = {
        y: [remote(f"pptx/cc-by-4.0/{y}/{i}.pptx") for i in range(10)] + [remote(f"pptx/cc-zero/{y}/big.pptx", 9 * MB)]
        for y in fc.ZENODO_YEARS
    }
    picks = fc.choose_zenodo(by_year, random.Random(1))
    assert len(picks) == 42 and all(p.size <= fc.MAX_BYTES for p in picks)
    assert {p.path.split("/")[2] for p in picks} == {str(y) for y in fc.ZENODO_YEARS}
    assert picks == fc.choose_zenodo(by_year, random.Random(1)), "the same seed picks the same decks"
    with pytest.raises(SystemExit, match="2018"):
        fc.choose_zenodo({**by_year, 2018: by_year[2018][:3]}, random.Random(1))


def test_slides_align_takes_three_decks_from_six_products_that_have_them():
    by_product = {f"P{i}": [remote(f"P{i}/cat/t{k}/t{k}.pptx") for k in range(5)] for i in range(8)}
    by_product["PDFOnly"] = [remote("PDFOnly/cat/t/t.pdf")]
    by_product["TooBig"] = [remote(f"TooBig/cat/t{k}/t{k}.pptx", 20 * MB) for k in range(5)]
    picks = fc.choose_slides_align(by_product, random.Random(2))
    products = {p.path.split("/")[0] for p in picks}
    assert len(picks) == 18 and len(products) == 6 and not products & {"PDFOnly", "TooBig"}


def test_datacluster_takes_the_three_smallest():
    files = [remote(f"PPT_Datasets/{n}.pptx", s) for n, s in [("a", 5), ("b", 1), ("c", 3), ("d", 2)]]
    assert [f.path for f in fc.choose_datacluster(files)] == [f"PPT_Datasets/{n}.pptx" for n in "bdc"]


def _deck(tmp_path, content=b"PK fake"):
    import hashlib

    return fc.Deck("src/a.pptx", "S", "mit", "A", "", "https://example/a.pptx", 1, len(content),
                   hashlib.sha256(content).hexdigest())  # fmt: skip


def test_a_second_run_downloads_nothing_and_a_damaged_file_again(tmp_path, monkeypatch):
    content = b"PK fake deck"
    deck = _deck(tmp_path, content)
    fetched = []

    def fake_download(url, dest, sha):
        fetched.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    monkeypatch.setattr(fc, "download", fake_download)
    fc.write_manifest(tmp_path / "manifest.csv", [deck])
    assert fc.read_manifest(tmp_path / "manifest.csv") == [deck]

    assert fc.main(["--data", str(tmp_path)]) == 0 and len(fetched) == 1
    assert fc.main(["--data", str(tmp_path)]) == 0 and len(fetched) == 1, "second run is a no-op"
    (tmp_path / "pptx" / deck.file).write_bytes(b"damaged")
    assert fc.main(["--data", str(tmp_path)]) == 0 and len(fetched) == 2, "a bad checksum is fetched again"


def test_the_summary_counts_findings_and_decks_per_rule_and_source():
    results = [
        {"file": "a", "source": "X", "findings": [{"code": "OVS101"}, {"code": "OVS101"}]},
        {"file": "b", "source": "Y", "findings": [{"code": "OVS101"}, {"code": "OVS004"}]},
        {"file": "c", "source": "Y", "findings": []},
    ]
    text = rc.summary(results, [{"file": "d", "source": "Y", "error": "ValueError: x"}], render=False)
    assert "4 findings; 2 of 3 decks have at least one" in text
    assert "| OVS101 text-too-small | 3 | 2 | 2 | 1 |" in text
    assert "| OVS004 frame-off-slide | 1 | 1 | 0 | 1 |" in text
    assert "overset crashed on 1 decks:\n- d: ValueError: x" in text


def test_running_over_a_tiny_corpus(builder, tmp_path):
    builder.text("Fine print", size=6)
    builder.save(tmp_path / "pptx.tmp")
    (tmp_path / "pptx" / "src").mkdir(parents=True)
    (tmp_path / "pptx.tmp").rename(tmp_path / "pptx" / "src" / "a.pptx")
    fc.write_manifest(tmp_path / "manifest.csv", [_deck(tmp_path)])
    assert rc.main(["--data", str(tmp_path)]) == 0
    summary = (tmp_path / "results" / "overset_norender_summary.txt").read_text()
    assert "| OVS101 text-too-small | 1 | 1 | 1 |" in summary
