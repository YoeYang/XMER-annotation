"""对齐的硬约束：可以摆不准，不能删词。"""
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from align import EnglishAligner, normalise_english, tokenize, _spell


@pytest.mark.parametrize(
    "number,spelled",
    [(3, "THREE"), (25, "TWENTY FIVE"), (40, "FORTY"), (100, "ONE HUNDRED")],
)
def test_numbers_become_words(number, spelled):
    """数字不展开就会被清成空串，模型不知道要给它留时间。"""
    assert _spell(number) == spelled


@pytest.mark.parametrize(
    "raw,expected",
    [("40?", "FORTY"), ("25", "TWENTY FIVE"), ("don't", "DON'T"), ('"', "")],
)
def test_normalisation(raw, expected):
    assert normalise_english(raw) == expected


def test_alignment_never_drops_a_token():
    """回归：纯标点和数字曾被静默丢弃，80 条试跑里漏了 7 个词。

    标注者读到的句子必须逐 token 等于数据集转录稿，否则和这个样本的
    冲突标签对不上。
    """
    aligner = EnglishAligner()
    words = tokenize('He said "no" - twice, 25 times.', chinese=False)
    silence = torch.zeros(1, 16000 * 3)
    result = aligner.align(silence, words)
    assert [w.text for w in result] == words


def test_chinese_tokenises_per_character():
    assert tokenize("吃起来像，带刺的鼻屎。", chinese=True)[:3] == ["吃", "起", "来"]
