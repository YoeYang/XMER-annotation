"""trackcore 的单元测试。全部用构造数据，不碰视频与 cv2。

边界值刻意避开被测逻辑的分界点——handover 记过一次教训：
采样测试让媒体时间正好停在栅格点上，末点收不收要看浮点误差，
三条断言无谓地红了。这里同理：相似度一律取 0.20 / 0.50 这种远离
SIM_ACCEPT=0.25 的值，检出率也避开 0.30 与 0.50 两个门槛本身，
除非某条测试就是在测边界。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import trackcore as tc


def face(x, y, w=100, h=120, det=0.95, sim=0.50):
    return {"bbox": [x, y, w, h], "det": det, "sim": sim}


FRAME_W, FRAME_H = 1920, 720
FPS = 25.0


def run(cands, w=FRAME_W, h=FRAME_H, fps=FPS):
    return tc.build(cands, fps, w, h)


# ---- iou ----

def test_iou_identical_is_one():
    assert tc.iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0


def test_iou_disjoint_is_zero():
    assert tc.iou([0, 0, 10, 10], [50, 50, 10, 10]) == 0.0


def test_iou_half_overlap():
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
    track = tc.link_track([[face(0, 0, sim=0.30), face(500, 0, sim=0.80)]], FRAME_H)
    assert track[0]["bbox"][0] == 500


def test_link_prefers_temporal_coherence_when_similarity_close():
    """两张脸相似度接近时，IoU 奖励应让轨迹跟住上一帧那个人。

    第 2 帧里 sim 更高的是远处那张（0.52 vs 0.50），但近处那张与上一帧完全重合，
    IoU 奖励 0.30 足以翻盘——这正是多人同框时不来回跳的机制。
    """
    cands = [[face(0, 0, sim=0.70)],
             [face(0, 0, sim=0.50), face(600, 0, sim=0.52)]]
    assert tc.link_track(cands, FRAME_H)[1]["bbox"][0] == 0


def test_link_rejects_below_accept_threshold():
    assert tc.link_track([[face(0, 0, sim=0.10)]], FRAME_H)[0] is None


def test_link_marks_undetected_frame_as_none():
    track = tc.link_track([[face(0, 0)], [], [face(0, 0)]], FRAME_H)
    assert track[1] is None


# ---- gaps ----

def test_gaps_finds_interior_run():
    assert tc.gaps([1, None, None, 1]) == [(1, 2)]


def test_gaps_finds_leading_and_trailing():
    assert tc.gaps([None, 1, None]) == [(0, 0), (2, 2)]


# ---- stable_box：尺寸 ----

def test_box_side_is_constant_across_frames():
    """固定尺寸是设计目标：缩放抖动会让标注者分心。"""
    cands = [[face(500, 300, w=100 + i * 5, h=120 + i * 5)] for i in range(20)]
    crop, _, _, _ = run(cands)
    assert crop["side"] > 0
    # side 是标量，本身就保证全段一致；这里确认它按高分位取、装得下最大的脸
    assert crop["side"] >= 195 * (1 + 2 * tc.CROP_MARGIN) * 0.9


def test_box_side_never_exceeds_frame():
    cands = [[face(100, 100, w=700, h=700)] for _ in range(10)]
    crop, _, _, _ = run(cands, w=800, h=600)
    assert crop["side"] <= 600


# ---- stable_box：静态 vs 慢速 ----

def test_static_mode_when_face_barely_moves():
    cands = [[face(500 + (i % 2), 300)] for i in range(30)]
    crop, _, _, _ = run(cands)
    assert crop["mode"] == "static"
    xs = {f["cx"] for f in crop["frames"]}
    assert len(xs) == 1


def test_slow_mode_when_face_crosses_frame():
    cands = [[face(100 + i * 40, 300)] for i in range(30)]
    crop, _, _, _ = run(cands)
    assert crop["mode"] == "slow"


def test_slow_mode_center_moves_gradually():
    """EMA 系数很小，中心不该在一帧之内跳到位。"""
    cands = [[face(100, 300)] for _ in range(15)] + [[face(1500, 300)] for _ in range(15)]
    crop, _, _, _ = run(cands)
    xs = [f["cx"] for f in crop["frames"]]
    steps = [abs(b - a) for a, b in zip(xs, xs[1:])]
    assert max(steps) < 400          # 真跳变会是 1400


# ---- stable_box：未检出帧 ----

def test_undetected_frames_keep_box_in_place():
    """检不出就把框留在原处——画面照常播真实帧，不冻结。"""
    cands = [[face(500, 300)], [], [], [face(520, 300)]]
    crop, _, _, _ = run(cands)
    assert len(crop["frames"]) == 4
    assert [f["present"] for f in crop["frames"]] == [1, 0, 0, 1]
    xs = [f["cx"] for f in crop["frames"]]
    assert max(xs) - min(xs) < 100


def test_leading_undetected_frames_hold_first_known_center():
    cands = [[], [], [face(800, 300)]]
    crop, _, _, _ = run(cands)
    assert crop["frames"][0]["present"] == 0
    assert abs(crop["frames"][0]["cx"] - crop["frames"][2]["cx"]) < 1e-6


def test_box_clamped_inside_frame():
    """脸贴着画面边缘时，框不能探到画外。"""
    cands = [[face(0, 0, w=200, h=200)] for _ in range(10)]
    crop, _, _, _ = run(cands, w=1920, h=720)
    half = crop["side"] / 2
    for f in crop["frames"]:
        assert f["cx"] >= half - 1e-6 and f["cy"] >= half - 1e-6
        assert f["cx"] <= 1920 - half + 1e-6 and f["cy"] <= 720 - half + 1e-6


def test_no_face_at_all_yields_no_crop():
    crop, stats, status, _ = run([[], [], []])
    assert crop is None and status == "drop" and stats["det_rate"] == 0.0


# ---- smooth_presence：防屏闪 ----

def test_short_dropout_is_held_visible():
    """一帧丢失不该切黑——照搬逐帧检出会产生高频黑白交替，看着像屏闪。"""
    present = [1] * 10 + [0] + [1] * 10
    assert tc.smooth_presence(present, FPS) == [1] * 21


def test_alternating_detection_becomes_steady():
    """一帧有一帧无（侧脸典型情形）应被整成全程可见。

    首尾刻意给检出帧：首尾的丢失是不填的（开头人还没出现、结尾人已经走了），
    拿 [0,1,0,1,...] 来测会把那条规则也一起测进来，断言就不纯粹了。
    """
    present = [1] + [i % 2 for i in range(38)] + [1]
    assert tc.smooth_presence(present, FPS) == [1] * 40


def test_long_dropout_still_goes_black():
    """连续丢失 1 秒（> HOLD_SECONDS 0.4s）是真的切镜头了，该黑屏。"""
    present = [1] * 20 + [0] * 25 + [1] * 20
    vis = tc.smooth_presence(present, FPS)
    assert sum(vis[20:45]) == 0


def test_single_frame_flash_inside_blackout_is_removed():
    """切走的镜头里偶尔蒙对一帧，会在黑屏里闪一下白，同样刺眼。"""
    present = [1] * 15 + [0] * 12 + [1] + [0] * 12 + [1] * 15
    vis = tc.smooth_presence(present, FPS)
    assert vis[27] == 0


def test_leading_and_trailing_dropout_not_filled():
    """开头还没出现人、结尾人已经走了，不该硬填成可见。"""
    present = [0] * 3 + [1] * 20 + [0] * 3
    vis = tc.smooth_presence(present, FPS)
    assert vis[0] == 0 and vis[-1] == 0


def test_empty_presence_does_not_crash():
    assert tc.smooth_presence([], FPS) == []


def test_flicker_cuts_counts_black_runs():
    cands = [[face(500, 300, sim=0.60)] if i < 15 or i >= 40 else []
             for i in range(55)]
    _, stats, _, _ = run(cands)
    assert stats["flicker_cuts"] == 1
    assert stats["black_ratio"] > 0


# ---- evaluate：新判据 ----

def test_all_detected_is_ok():
    crop, stats, status, reasons = run([[face(500, 300, sim=0.60)] for _ in range(40)])
    assert status == "ok" and reasons == []
    assert stats["face_present_ratio"] == 1.0
    assert stats["black_ratio"] == 0.0
    assert all(f["visible"] == 1 for f in crop["frames"])


def test_side_profile_gaps_no_longer_fail_the_sample():
    """整段有 30% 的帧检不出（侧脸），仍应判 ok。

    这正是改版的目的：旧口径用「最大连续空洞 > 0.5s」判刑，
    把 meld / mustard 这类反打镜头多的源误杀了 22% 与 52%。
    """
    cands = [[] if 10 <= i < 22 else [face(500, 300, sim=0.60)] for i in range(40)]
    _, stats, status, _ = run(cands)
    assert stats["max_gap_seconds"] > 0.4      # 空洞确实很长
    assert status == "ok"                      # 但不再因此判刑


# ---- coverage：定 margin 的依据 ----

def test_coverage_is_full_when_face_stays_put():
    cands = [[face(500, 300, sim=0.60)] for _ in range(20)]
    _, stats, _, _ = run(cands)
    assert stats["face_inside_ratio"] == 1.0


def test_coverage_drops_when_margin_too_tight():
    """脸在框内来回移动时，收紧 margin 会让一部分帧的脸探出框外。

    这正是用数据定 margin 的理由：不靠拍脑袋，看这个比例掉到哪。
    """
    cands = [[face(500 + (0 if i % 2 else 120), 300, sim=0.60)] for i in range(20)]
    loose = tc.build(cands, FPS, FRAME_W, FRAME_H, margin=0.60)[1]["face_inside_ratio"]
    tight = tc.build(cands, FPS, FRAME_W, FRAME_H, margin=0.05)[1]["face_inside_ratio"]
    assert loose > tight


def test_black_screen_over_seventy_percent_is_dropped():
    """可见率 0.20 = 黑屏 80% > 70% 上限 —— 这条做不了 face/body。"""
    cands = [[face(500, 300, sim=0.60)] if i < 8 else [] for i in range(40)]
    _, stats, status, reasons = run(cands)
    assert status == "drop" and any("visible" in r for r in reasons)
    assert stats["black_ratio"] > 0.70


def test_forty_percent_detection_still_usable():
    """检出率 0.40 = 黑屏 60%，在 70% 上限之内 —— 判 low_confidence，不判死。"""
    cands = [[face(500, 300, sim=0.60)] if i < 16 else [] for i in range(40)]
    _, stats, status, _ = run(cands)
    assert abs(stats["visible_ratio"] - 0.40) < 1e-9
    assert status == "low_confidence"


def test_ample_detection_is_ok():
    cands = [[face(500, 300, sim=0.60)] if i < 28 else [] for i in range(40)]
    _, _, status, _ = run(cands)
    assert status == "ok"


def test_wrong_identity_is_dropped():
    """单帧都过了 SIM_ACCEPT，但均值低于同人阈值 → 跟错人，不是检不出。"""
    _, _, status, reasons = run([[face(500, 300, sim=0.30)] for _ in range(40)])
    assert status == "drop" and any("mean_sim" in r for r in reasons)


def test_empty_track_does_not_crash():
    stats, status, reasons = tc.evaluate([None] * 10, FPS, FRAME_H)
    assert status == "drop" and stats["det_rate"] == 0.0


# ---- build 整体 ----

def test_crop_frames_carry_raw_bbox_for_body_masking():
    """body 的遮挡要跟着每帧实际检到的框走，所以 bbox 必须逐帧落盘。

    face 用的是 cx/cy + side 那个稳定大框（要稳），body 用这个真框（要准）。
    两者刻意不共用：拿稳定框去遮，镜头一切就盖到旁边人脸上了。
    """
    cands = [[face(500, 300, sim=0.60)] for _ in range(10)]
    cands[4] = []
    crop, _, _, _ = run(cands)
    assert crop["frames"][0]["bbox"] == [500.0, 300.0, 100.0, 120.0]
    assert crop["frames"][4]["bbox"] is None      # 没检出就没框，body 该帧不遮


def test_body_bbox_is_independent_of_visible_hysteresis():
    """迟滞只影响 face 的黑屏判定，不该把 bbox 也填出来。

    第 5 帧检不出但迟滞会把它算作 visible（短暂丢失继续显示画面）；
    然而 body 在这一帧**没有真框可用**，就不该遮。
    """
    cands = [[face(500, 300, sim=0.60)] for _ in range(20)]
    cands[5] = []
    crop, _, _, _ = run(cands)
    assert crop["frames"][5]["visible"] == 1      # face：继续显示，不闪
    assert crop["frames"][5]["bbox"] is None      # body：无框可遮，不乱遮


def test_build_reports_present_flags_matching_detection():
    cands = [[face(500, 300, sim=0.60)] for _ in range(20)]
    cands[5] = []
    crop, stats, _, _ = run(cands)
    assert sum(f["present"] for f in crop["frames"]) == 19
    assert stats["detected"] == 19


def test_build_handles_non_25_fps():
    """中值窗按秒取而不是按帧，30fps 素材不该出问题。"""
    cands = [[face(500, 300, sim=0.60)] for _ in range(60)]
    crop, _, status, _ = run(cands, fps=30.0)
    assert status == "ok" and len(crop["frames"]) == 60
