"""人脸特征库：用单人桶自动建角色原型，再给多人桶做身份匹配。

meld / mustard 的单人桶样本「一张脸 + 已知角色名」本身就是带标签的人脸库，
不需要手工标注也不需要调 API。但这批标签有噪声——反应镜头（画面是听话人特写、
说话人在画外）会把错的脸挂在说话人名下——所以建库时按角色做聚类，只取最大簇当原型。

识别用 OpenCV 的 SFace，与检测用的 YuNet 同属 opencv_zoo 一套，
YuNet 的五点关键点正好是 SFace 对齐所需的输入，不引入新依赖。
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT, main_faces

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datapaths import FRAMES_DIR  # noqa: E402

SFACE = FRAMES_DIR / "models/face_recognition_sface_2021dec.onnx"
EMBEDS = OUT / "embeds.npz"

# SFace 官方推荐的余弦同人阈值；建库聚类用它，匹配门限另外标定
SAME_COSINE = 0.363
MIN_GALLERY = 3          # 原型至少要这么多张脸才可信，否则该角色降级走 Gemini

_rec = None


def recognizer():
    global _rec
    if _rec is None:
        import cv2
        _rec = cv2.FaceRecognizerSF.create(str(SFACE), "")
    return _rec


def face_row(face):
    """把扫描结果里的 face dict 还原成 SFace alignCrop 需要的 15 维行向量。"""
    return np.array(face["bbox"] + face["kps"] + [face["det"]], dtype=np.float32)


def embed(frame, face):
    """返回 L2 归一化后的 128 维特征。"""
    rec = recognizer()
    aligned = rec.alignCrop(frame, face_row(face))
    feat = rec.feature(aligned).flatten().astype(np.float32)
    n = np.linalg.norm(feat)
    return feat / n if n else feat


def cosine(a, b):
    return float(np.dot(a, b))


def largest_cluster(feats, thresh=SAME_COSINE):
    """返回最大簇的下标。

    先按阈值建同人图，取最大连通分量——反应镜头的错脸彼此不相似，
    会散成一堆孤立点，而真正的角色脸互相连成一大片。
    """
    n = len(feats)
    if n == 0:
        return []
    if n == 1:
        return [0]
    sim = feats @ feats.T
    adj = sim >= thresh
    seen = np.zeros(n, dtype=bool)
    best = []
    for i in range(n):
        if seen[i]:
            continue
        stack, comp = [i], []
        seen[i] = True
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in np.nonzero(adj[u] & ~seen)[0]:
                seen[v] = True
                stack.append(int(v))
        if len(comp) > len(best):
            best = comp
    return sorted(best)


def build_gallery(embeds_by_name, min_size=MIN_GALLERY):
    """embeds_by_name: {角色名: (sample_ids, feats[N,128])}

    返回 (gallery, stats)。gallery: {角色名: 原型向量}，
    stats 记录每个角色进了多少、留了多少、被判为离群的是哪些样本。
    """
    gallery, stats = {}, {}
    for name, (sids, feats) in embeds_by_name.items():
        keep = largest_cluster(feats)
        outliers = [sids[i] for i in range(len(sids)) if i not in set(keep)]
        st = {"n_in": len(sids), "n_keep": len(keep), "outliers": outliers}
        if len(keep) >= min_size:
            proto = feats[keep].mean(axis=0)
            proto /= np.linalg.norm(proto) or 1.0
            gallery[name] = proto
            st["usable"] = True
        else:
            st["usable"] = False       # 库存太薄，不建原型，该角色回退 Gemini
        stats[name] = st
    return gallery, stats


def save_embeds(path, sample_ids, names, feats):
    np.savez_compressed(path, sample_ids=np.array(sample_ids),
                        names=np.array(names), feats=np.asarray(feats, dtype=np.float32))


def load_embeds(path):
    d = np.load(path, allow_pickle=False)
    return list(d["sample_ids"]), list(d["names"]), d["feats"]
