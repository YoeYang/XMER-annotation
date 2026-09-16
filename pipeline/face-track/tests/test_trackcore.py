"""trackcore 的单元测试。全部用构造数据，不碰视频与 cv2。

边界值刻意避开被测逻辑的分界点——handover 记过一次教训：
采样测试让媒体时间正好停在栅格点上，末点收不收要看浮点误差，
三条断言无谓地红了。这里同理：相似度一律取 0.20 / 0.50 这种远离
SIM_ACCEPT=0.25 的值，除非某条测试就是在测边界。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import trackcore as tc


def face(x, y, w=100, h=120, det=0.95, sim=0.50):
    return {"bbox": [x, y, w, h], "det": det, "sim": sim}


FRAME_H = 720


# ---- iou ----

def test_iou_identical_is_one():
    assert tc.iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0


def test_iou_disjoint_is_zero():
    assert tc.iou([0, 0, 10, 10], [50, 50, 10, 10]) == 0.0


def test_iou_half_overlap():
    # 两个 10x10 框横向错开 5 → 交 50，并 150
    assert abs(tc.iou([0, 0, 10, 10], [5, 0, 10, 10]) - 50 / 150) < 1e-9


# ---- filter_candidates ----

def test_filter_drops_low_confidence():
    faces = [face(0, 0, det=0.50), face(200, 0, det=0.95)]
    assert [f["bbox"][0] for f in tc.filter_candidates(faces, FRAME_H)] == [200]


def test_filter_drops_tiny_face():
    # 脸高 20 < 7% * 720 = 50.4
    faces = [face(0, 0, h=20), face(200, 0, h=120)]
    assert [f["bbox"][0] for f in tc.filter_candidates(faces, FRAME_H)] == [200]


# ---- link_track ----

def test_link_picks_highest_similarity():
    cands = [[face(0, 0, sim=0.30), face(500, 0, sim=0.80)]]
    track = tc.link_track(cands, FRAME_H)
    assert track[0]["bbox"][0] == 500
    assert track[0]["src"] == "det"


def test_link_prefers_temporal_coherence_when_similarity_close():
    """两张脸相似度接近时，IoU 奖励应让轨迹跟住上一帧那个人。

    第 2 帧里 sim 更高的是远处那张（0.52 vs 0.50），但近处那张与上一帧完全重合，
    IoU 奖励 0.30 足以翻盘——这正是多人同框时不来回跳的机制。
    """
    cands = [
        [face(0, 0, sim=0.70)],
        [face(0, 0, sim=0.50), face(600, 0, sim=0.52)],
    ]
    track = tc.link_track(cands, FRAME_H)
    assert track[1]["bbox"][0] == 0


def test_link_rejects_below_accept_threshold():
    cands = [[face(0, 0, sim=0.10)]]
    assert tc.link_track(cands, FRAME_H)[0] is None


def test_link_marks_empty_frame_as_gap():
    cands = [[face(0, 0)], [], [face(0, 0)]]
    track = tc.link_track(cands, FRAME_H)
    assert track[1] is None


# ---- gaps / fill_gaps ----

def test_gaps_finds_interior_run():
    track = [1, None, None, 1]
    assert tc.gaps(track) == [(1, 2)]


def test_gaps_finds_leading_and_trailing():
    track = [None, 1, None]
    assert tc.gaps(track) == [(0, 0), (2, 2)]


def test_fill_interpolates_linearly():
    cands = [[face(0, 0)], [], [face(100, 0)]]
    track = tc.fill_gaps(tc.link_track(cands, FRAME_H))
    assert track[1]["src"] == "interp"
    assert abs(track[1]["bbox"][0] - 50.0) < 1e-9


def test_fill_extrapolates_leading_gap_by_holding():
    cands = [[], [face(80, 0)]]
    track = tc.fill_gaps(tc.link_track(cands, FRAME_H))
    assert track[0]["bbox"][0] == 80.0
    assert track[0]["src"] == "interp"


def test_fill_on_all_missing_leaves_none():
    track = tc.fill_gaps(tc.link_track([[], []], FRAME_H))
    assert track == [None, None]


# ---- smooth ----

def test_smooth_suppresses_single_frame_spike():
    """一帧的脉冲跳变应被中值窗吃掉，不该把整条轨迹带偏。"""
    cands = [[face(100, 0)] for _ in range(9)]
    cands[4] = [face(400, 0)]          # 中间一帧跳到远处
    track = tc.link_track(cands, FRAME_H)
    tc.smooth(track)
    assert track[4]["bbox"][0] < 150


def test_smooth_keeps_provenance_fields():
    cands = [[face(100, 0, det=0.9, sim=0.6)] for _ in range(5)]
    track = tc.smooth(tc.link_track(cands, FRAME_H))
    assert track[0]["det"] == 0.9 and track[0]["sim"] == 0.6
    assert track[0]["src"] == "det"


def test_smooth_noop_on_single_frame():
    track = tc.link_track([[face(100, 0)]], FRAME_H)
    assert tc.smooth(track)[0]["bbox"][0] == 100


# ---- evaluate ----

def test_evaluate_clean_track_is_ok():
    cands = [[face(100, 0, sim=0.60)] for _ in range(50)]
    track = tc.fill_gaps(tc.link_track(cands, FRAME_H))
    stats, status, reasons = tc.evaluate(track, 25, FRAME_H)
    assert status == "ok" and reasons == []
    assert stats["det_rate"] == 1.0 and stats["missing"] == 0


def test_evaluate_flags_low_detection_rate():
    cands = [[face(100, 0, sim=0.60)] if i < 20 else [] for i in range(50)]
    track = tc.fill_gaps(tc.link_track(cands, FRAME_H))
    _, status, reasons = tc.evaluate(track, 25, FRAME_H)
    assert any("det_rate" in r for r in reasons)
    assert status in ("low_confidence", "drop")


def test_evaluate_flags_long_gap():
    """25fps 下连续缺 20 帧 = 0.8s > 0.5s 上限。"""
    cands = [[] if 10 <= i < 30 else [face(100, 0, sim=0.60)] for i in range(50)]
    track = tc.fill_gaps(tc.link_track(cands, FRAME_H))
    stats, _, reasons = tc.evaluate(track, 25, FRAME_H)
    assert stats["max_gap_frames"] == 20
    assert any("max_gap" in r for r in reasons)


def test_evaluate_flags_wrong_identity():
    """单帧都过了 SIM_ACCEPT，但均值低于 SFace 同人阈值 → 跟错人。"""
    cands = [[face(100, 0, sim=0.30)] for _ in range(50)]
    track = tc.fill_gaps(tc.link_track(cands, FRAME_H))
    _, status, reasons = tc.evaluate(track, 25, FRAME_H)
    assert any("mean_sim" in r for r in reasons)


def test_evaluate_two_reasons_becomes_drop():
    cands = [[face(100, 0, sim=0.30)] if i < 20 else [] for i in range(50)]
    track = tc.fill_gaps(tc.link_track(cands, FRAME_H))
    _, status, reasons = tc.evaluate(track, 25, FRAME_H)
    assert len(reasons) >= 2 and status == "drop"


def test_evaluate_empty_track_does_not_crash():
    stats, status, reasons = tc.evaluate([None] * 10, 25, FRAME_H)
    assert status == "drop" and stats["det_rate"] == 0.0


# ---- build ----

def test_build_end_to_end():
    cands = [[face(100 + i, 0, sim=0.60)] for i in range(40)]
    cands[10] = []
    track, stats, status, reasons = tc.build(cands, 25, FRAME_H)
    assert status == "ok"
    assert stats["interpolated"] == 1
    assert all(t is not None for t in track)
