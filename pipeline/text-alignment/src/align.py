"""对已知转录稿做强制对齐，得到词级时间戳。

**不做语音识别。** 转录稿来自数据集，是"仅文本"模态给标注者看的内容，
也是 04 冲突判定的依据；让模型自己听写会改动这份文本，整条冲突链就断了。
模型只负责把已知的词摆到时间轴上。
"""

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile
import torch
import torchaudio

SAMPLE_RATE = 16000
# 计算节点是 ARM(GH200)，登录节点同架构；有卡就用卡，没有就退回 CPU
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class Word:
    text: str
    start: float
    end: float
    score: float


def audio_source(video: Path) -> Path:
    """返回该样本真正带声音的文件。

    MUStARD 的 video.mp4 **没有音轨**，声音在同目录的 audio.wav 里。
    直接对 video.mp4 抽音频会得到空流，ffmpeg 报错退出。
    """
    if video.name == "video.mp4":
        sibling = video.with_name("audio.wav")
        if sibling.exists():
            return sibling
    return video


def extract_audio(video: Path) -> torch.Tensor:
    """抽 16kHz 单声道波形。对齐模型只吃这个采样率。"""
    video = audio_source(video)
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(video),
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "wav", tmp.name],
            check=True,
        )
        # torchaudio 2.11 的 load 改依赖 torchcodec（本机未装），直接用 soundfile
        data, rate = soundfile.read(tmp.name, dtype="float32", always_2d=True)
    assert rate == SAMPLE_RATE, rate
    return torch.from_numpy(np.ascontiguousarray(data.T))


def tokenize(text: str, chinese: bool) -> list[str]:
    """中文按字切，英文按空白切。

    中文没有词边界，逐字呈现本来就是这个模态想要的节奏；
    强行分词反而引入一层可错的判断。
    """
    text = text.strip()
    if chinese:
        return [c for c in re.sub(r"\s+", "", text) if c.strip()]
    return [w for w in re.split(r"\s+", text) if w]


_ONES = ("ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE "
         "THIRTEEN FOURTEEN FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN").split()
_TENS = ("  TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY").split()


def _spell(number: int) -> str:
    """把整数念成英文。数字在转录稿里是会被说出口的词，
    不展开的话对齐模型看不见它，会把它的时长并给相邻词。"""
    if number < 20:
        return _ONES[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return _TENS[tens - 2] + (" " + _ONES[ones] if ones else "")
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        return _ONES[hundreds] + " HUNDRED" + (" " + _spell(rest) if rest else "")
    if number < 1_000_000:
        thousands, rest = divmod(number, 1000)
        return _spell(thousands) + " THOUSAND" + (" " + _spell(rest) if rest else "")
    return " ".join(_ONES[int(d)] for d in str(number))


def normalise_english(word: str) -> str:
    """转成模型标签表里的形态：大写、只留字母和撇号。

    数字先展开成英文单词——否则 "25 years" 里的 25 会被清成空串，
    模型不知道要给它留时间，那段时长会被并进相邻词。
    """
    expanded = re.sub(
        r"\d+", lambda m: " " + _spell(int(m.group())) + " ", word
    )
    return re.sub(r"[^A-Z' ]", "", expanded.upper()).strip()


class EnglishAligner:
    def __init__(self) -> None:
        bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        self.model = bundle.get_model().to(DEVICE)
        self.model.eval()
        self.labels = bundle.get_labels()
        self.index = {label: i for i, label in enumerate(self.labels)}

    def align(self, waveform: torch.Tensor, words: list[str]) -> list[Word]:
        """返回与输入 `words` **等长**的结果。

        对齐可以摆不准，但绝不能删词：展示给标注者的文本必须逐 token 等于
        数据集转录稿。声学上对不上的 token（纯标点等）由相邻词插值定位，
        并以 score=-1 标出，便于事后追查。
        """
        cleaned = [normalise_english(w) for w in words]
        usable = [(i, w) for i, w in enumerate(cleaned) if w]
        if not usable:
            return [Word(w, 0.0, 0.0, -1.0) for w in words]

        with torch.inference_mode():
            emission, _ = self.model(waveform.to(DEVICE))
            emission = torch.log_softmax(emission, dim=-1).cpu()

        tokens, spans = [], []
        for _, word in usable:
            start = len(tokens)
            for char in word:
                if char in self.index:
                    tokens.append(self.index[char])
            spans.append((start, len(tokens)))

        targets = torch.tensor([tokens], dtype=torch.int32)
        aligned, scores = torchaudio.functional.forced_align(
            emission, targets, blank=0
        )
        aligned, scores = aligned[0], scores[0].exp()
        spans_tok = torchaudio.functional.merge_tokens(aligned, scores)

        ratio = waveform.size(1) / emission.size(1) / SAMPLE_RATE
        placed: dict[int, Word] = {}
        for (original_index, _), (lo, hi) in zip(usable, spans):
            pieces = spans_tok[lo:hi]
            if not pieces:
                continue
            placed[original_index] = Word(
                text=words[original_index],
                start=round(pieces[0].start * ratio, 3),
                end=round(pieces[-1].end * ratio, 3),
                score=round(sum(p.score for p in pieces) / len(pieces), 3),
            )

        out: list[Word] = []
        for index, text in enumerate(words):
            if index in placed:
                out.append(placed[index])
                continue
            before = max((i for i in placed if i < index), default=None)
            after = min((i for i in placed if i > index), default=None)
            if before is not None and after is not None:
                moment = (placed[before].end + placed[after].start) / 2
            elif before is not None:
                moment = placed[before].end
            elif after is not None:
                moment = placed[after].start
            else:
                moment = 0.0
            out.append(Word(text, round(moment, 3), round(moment, 3), -1.0))

        # 展示给标注者的文本必须逐 token 等于数据集转录稿。
        # 漏词会让标注者读到的句子和这个样本的冲突标签对不上。
        assert len(out) == len(words), (len(out), len(words))
        assert [w.text for w in out] == words
        return out


class ChineseAligner:
    """中文用 wav2vec2 中文 CTC 模型，按**字**对齐。

    中文没有词边界，逐字呈现本来就是这个模态要的节奏；强行分词反而
    多引入一层可错的判断。模型词表本身也是字级的。
    """

    MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"

    def __init__(self) -> None:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        self.processor = Wav2Vec2Processor.from_pretrained(self.MODEL)
        self.model = Wav2Vec2ForCTC.from_pretrained(self.MODEL).to(DEVICE)
        self.model.eval()
        self.vocab = self.processor.tokenizer.get_vocab()
        self.blank = self.processor.tokenizer.pad_token_id

    def align(self, waveform: torch.Tensor, chars: list[str]) -> list[Word]:
        keep = [(i, c) for i, c in enumerate(chars) if c in self.vocab]
        if not keep:
            return [Word(c, 0.0, 0.0, -1.0) for c in chars]

        with torch.inference_mode():
            logits = self.model(waveform.to(DEVICE)).logits
            emission = torch.log_softmax(logits, dim=-1).cpu()

        targets = torch.tensor([[self.vocab[c] for _, c in keep]], dtype=torch.int32)
        aligned, scores = torchaudio.functional.forced_align(
            emission, targets, blank=self.blank
        )
        merged = torchaudio.functional.merge_tokens(aligned[0], scores[0].exp())

        ratio = waveform.size(1) / emission.size(1) / SAMPLE_RATE
        placed = {
            index: Word(
                text=chars[index],
                start=round(piece.start * ratio, 3),
                end=round(piece.end * ratio, 3),
                score=round(float(piece.score), 3),
            )
            for (index, _), piece in zip(keep, merged)
        }

        out: list[Word] = []
        for index, char in enumerate(chars):
            if index in placed:
                out.append(placed[index])
                continue
            before = max((i for i in placed if i < index), default=None)
            after = min((i for i in placed if i > index), default=None)
            if before is not None and after is not None:
                moment = (placed[before].end + placed[after].start) / 2
            elif before is not None:
                moment = placed[before].end
            elif after is not None:
                moment = placed[after].start
            else:
                moment = 0.0
            out.append(Word(char, round(moment, 3), round(moment, 3), -1.0))

        assert [w.text for w in out] == chars
        return out
