"""scripts/label_corpus.py, score_labels.py and rank_eval.py, without the network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_corpus as fc  # noqa: E402
import label_corpus as lc  # noqa: E402
import rank_eval as re_  # noqa: E402
import score_labels as sl  # noqa: E402


def test_the_sheet_takes_half_reported_and_half_unreported_slides_per_rule():
    found = {("a.pptx", n, "OVS202"): "stretched" for n in range(1, 30)}
    slides = [(f, n) for f in ("a.pptx", "b.pptx") for n in range(1, 40)]
    rows = lc.sheet(found, slides, ["OVS202"], per_rule=20)
    assert len(rows) == 20
    assert sum(r["overset"] == "yes" for r in rows) == 10 and sum(r["overset"] == "no" for r in rows) == 10
    assert all(r["defect"] == "" for r in rows)
    assert rows == lc.sheet(found, slides, ["OVS202"], per_rule=20), "the same seed gives the same sheet"


def test_scores_count_each_cell_and_leave_unsure_out(tmp_path):
    sheet = tmp_path / "sheet.csv"
    sheet.write_text(
        "file,slide,code,overset,message,defect,labeller,note\n"
        "a,1,OVS202,yes,,yes,ab,\n"
        "a,2,OVS202,yes,,no,ab,\n"
        "a,3,OVS202,no,,yes,ab,\n"
        "a,4,OVS202,no,,no,ab,\n"
        "a,5,OVS202,no,,unsure,ab,\n"
    )
    labels = sl.read_labels(sheet)
    assert len(labels) == 4
    predicted = {("a", 1, "OVS202"): True, ("a", 2, "OVS202"): True, ("a", 3, "OVS202"): False,
                 ("a", 4, "OVS202"): False}  # fmt: skip
    (s,) = sl.scores(labels, predicted).values()
    assert (s["tp"], s["fp"], s["fn"], s["tn"]) == (1, 1, 1, 1)
    assert s["precision"] == 0.5 and s["recall"] == 0.5
    assert "| OVS202 | 50% | 50% | 1 | 1 | 1 | 1 |" in sl.table(sl.scores(labels, predicted))


def test_scoring_runs_overset_on_the_labelled_decks(builder, tmp_path):
    builder.picture(size=(400, 200), w=4, h=4)  # stretched 100%
    (tmp_path / "pptx").mkdir()
    builder.save(tmp_path / "pptx" / "d.pptx")
    labels = {("d.pptx", 1, "OVS202"): True}
    from overset.settings import Settings

    assert sl.predictions(labels, tmp_path, Settings(render=False)) == {("d.pptx", 1, "OVS202"): True}
    lenient = Settings(render=False, max_aspect_distortion=2.0)
    assert sl.predictions(labels, tmp_path, lenient) == {("d.pptx", 1, "OVS202"): False}


def test_tau_b_and_pairwise_agreement():
    assert re_.tau_b([1, 2, 3], [0.1, 0.2, 0.3]) == pytest.approx(1)
    assert re_.tau_b([1, 2, 3], [0.3, 0.2, 0.1]) == pytest.approx(-1)
    assert re_.tau_b([1, 2, 3], [0.1, 0.1, 0.1]) is None
    assert re_.tau_b([1, 2, 3, 4], [0.1, 0.1, 0.3, 0.2]) == pytest.approx(0.5477, abs=1e-3)
    # Rank 1 has fewer findings than rank 3: agrees. A tie in findings decides nothing.
    assert re_.agreement([(1 - 3, 0.1 - 0.5), (2 - 3, 0.2 - 0.2), (1 - 2, 0.4 - 0.1)]) == (1, 2)


def test_topics_need_enough_products_with_a_small_enough_deck():
    ranks = {("cat", "T1"): {"Gamma": 1, "Skywork": 2, "Zhipu": 3, "Quake": 4, "Kimi-Smart": 5},
             ("cat", "T2"): {"Gamma": 1, "Zhipu": 2}}  # fmt: skip
    entry = {"path": "x", "size": 1, "sha256": ""}
    index = {(p, "T1"): entry for p in ("Gamma", "Skyworks", "Zhipu", "Quake", "Kimi-Smart")}
    index[("Gamma", "T2")] = entry
    chosen = re_.choose(ranks, index, 10, __import__("random").Random(1))
    assert list(chosen) == [("cat", "T1")] and "Skywork" in chosen[("cat", "T1")], "Skywork is the Skyworks folder"
    assert fc.MAX_BYTES < re_.MAX_BYTES
