import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from transcript import build, split_sentences, validate


def words(*triples):
    return [{"t": t, "s": s, "e": e} for t, s, e in triples]


def test_zero_width_tokens_get_positive_duration():
    """插值定位的标点 start==end，直接落盘会被标注页整个拒掉。"""
    doc = build(words(("Hi", 0.0, 0.5), ('"', 0.5, 0.5), ("there.", 0.6, 1.0)), 2.0)
    validate(doc, 2.0)
    for sentence in doc["sentences"]:
        for token in sentence["tokens"]:
            assert token["end"] > token["start"]


def test_overlapping_tokens_are_pushed_apart():
    doc = build(words(("a", 0.0, 0.6), ("b", 0.3, 0.8)), 2.0)
    validate(doc, 2.0)
    tokens = doc["sentences"][0]["tokens"]
    assert tokens[1]["start"] >= tokens[0]["end"]


def test_times_never_exceed_the_media_duration():
    """超出时长的 token 会被标注页拒收，等比压缩保序也保正时长。"""
    doc = build(words(("a", 0.0, 1.0), ("b", 1.0, 9.0)), 2.0)
    validate(doc, 2.0)
    assert doc["sentences"][-1]["end"] <= 2.0


def test_sentences_split_on_terminal_punctuation():
    groups = split_sentences(words(("Hi.", 0, 1), ("Go", 1, 2), ("now!", 2, 3)))
    assert [len(g) for g in groups] == [1, 2]


def test_chinese_terminals_split_too():
    groups = split_sentences(words(("像", 0, 1), ("。", 1, 2), ("好", 2, 3)))
    assert [len(g) for g in groups] == [2, 1]


def test_text_with_no_terminal_still_makes_one_sentence():
    doc = build(words(("no", 0.0, 0.4), ("stop", 0.4, 0.9)), 3.0)
    validate(doc, 3.0)
    assert len(doc["sentences"]) == 1


def test_validate_rejects_a_bad_document():
    bad = {"duration": 2.0, "sentences": [
        {"start": 0.0, "end": 1.0, "tokens": [
            {"start": 0.0, "end": 0.0, "text": "x"}]}]}
    with pytest.raises(ValueError):
        validate(bad, 2.0)
