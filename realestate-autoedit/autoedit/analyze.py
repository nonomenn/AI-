"""素材動画の解析: 「移動中」「手ブレ」「ピンボケ」を除いた、見せられる安定区間を自動で切り出す。

考え方(参考動画の分析より):
  高級感のある映像 = ジンバルでゆっくり一定速度で動いているカット。
  逆に使わない部分 = 部屋から部屋への移動(速い・前後に揺れる)、振り返り、急なパン、暗転・ピンボケ。
  → カメラの動きをオプティカルフローで推定し、「ゆっくり・滑らか・シャープ」な区間だけを残す。
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .media import gray_frames, probe


@dataclass
class Segment:
    clip: str
    start: float
    end: float
    fps: float
    width: int
    height: int
    score: float = 0.0            # 映像としての安定度(0〜1)
    speed: float = 0.0            # 平均カメラ速度
    direction: tuple = (0.0, 0.0, 0.0)  # 平均の動き (横, 縦, 前後)
    room: str = "other"          # AIが判定した部屋の種類
    beauty: float = 5.0           # AIが判定した「映え度」(0〜10)
    is_transit: bool = False      # 移動中のカットか(AI判定)
    note: str = ""
    id: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2

    def to_dict(self):
        d = asdict(self)
        d["duration"] = round(self.duration, 2)
        return d


def _global_motion(prev, cur):
    """前フレーム→現フレームのカメラの動き(平行移動・拡大率)を推定。"""
    pts = cv2.goodFeaturesToTrack(prev, maxCorners=300, qualityLevel=0.01, minDistance=8)
    if pts is None or len(pts) < 12:
        return None
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, winSize=(21, 21), maxLevel=3)
    good0 = pts[st.flatten() == 1]
    good1 = nxt[st.flatten() == 1]
    if len(good0) < 12:
        return None
    m, _ = cv2.estimateAffinePartial2D(good0, good1, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if m is None:
        return None
    s = float(np.hypot(m[0, 0], m[1, 0]))
    return float(m[0, 2]), float(m[1, 2]), float(np.log(max(s, 1e-6)))


def _smooth(x, win):
    if win < 2 or len(x) < win:
        return x.copy()
    k = np.ones(win) / win
    pad = win // 2
    xp = np.pad(x, (pad, win - 1 - pad), mode="edge")
    return np.convolve(xp, k, mode="valid")


def analyze_clip(path: str, cfg: dict) -> tuple[list[Segment], dict]:
    """1本の動画を解析し、使える区間(Segment)のリストと、デバッグ用の時系列を返す。"""
    a = cfg["analyze"]
    pr = probe(path)
    fps, W, H = pr.fps, pr.width, pr.height
    dt = 1.0 / a["sample_hz"]

    times, grays, sharp, bright = [], [], [], []
    for i, g in enumerate(gray_frames(path, a["sample_hz"])):
        times.append(i * dt)
        grays.append(g)
        sharp.append(cv2.Laplacian(g, cv2.CV_64F).var())
        bright.append(g.mean())
    if len(grays) < 3:
        return [], {}

    gw, gh = grays[0].shape[1], grays[0].shape[0]
    vx, vy, vz, cut = [0.0], [0.0], [0.0], [False]
    for i in range(1, len(grays)):
        mo = _global_motion(grays[i - 1], grays[i])
        # カット点(編集済み素材が混ざっていた場合)の検出: 輝度ヒストグラムの急変
        h0 = cv2.calcHist([grays[i - 1]], [0], None, [32], [0, 256]).flatten()
        h1 = cv2.calcHist([grays[i]], [0], None, [32], [0, 256]).flatten()
        hist_d = cv2.compareHist(h0.astype("float32"), h1.astype("float32"), cv2.HISTCMP_BHATTACHARYYA)
        if mo is None:
            vx.append(1.0); vy.append(1.0); vz.append(0.0)  # 追跡失敗 = 速すぎる/真っ白 → 不採用扱い
        else:
            vx.append(mo[0] / gw / dt); vy.append(mo[1] / gh / dt); vz.append(mo[2] / dt)
        cut.append(hist_d > 0.35)

    vx, vy, vz = map(np.array, (vx, vy, vz))
    t = np.array(times)
    win = max(3, int(round(0.7 / dt)))
    sx, sy, sz = _smooth(vx, win), _smooth(vy, win), _smooth(vz, win)
    # 速度: 横・縦の移動 + 前後移動(ズーム成分)。歩いて移動中は前後成分が大きく、縦揺れも出る
    speed = np.hypot(sx, sy) + 0.6 * np.abs(sz)
    # 手ブレ: 滑らかな動きからのズレ(高周波成分)
    resid = np.hypot(vx - sx, vy - sy) * dt
    shake = np.sqrt(_smooth(resid ** 2, win))
    sharp = np.array(sharp)
    sharp_ratio = sharp / (np.median(sharp) + 1e-6)
    bright = np.array(bright)

    good = (
        (speed < a["max_speed"])
        & (shake < a["max_shake"])
        & (sharp_ratio > a["min_sharpness_ratio"])
        & (bright > 25) & (bright < 235)
    )
    cuts = np.array(cut)

    # 連続した good 区間を抽出(カット点で分割)
    segs: list[Segment] = []
    i = 0
    L = len(t)
    while i < L:
        if not good[i]:
            i += 1
            continue
        j = i
        while j + 1 < L and good[j + 1] and not cuts[j + 1]:
            j += 1
        st, en = t[i] + a["trim_edges"], t[j] + dt - a["trim_edges"]
        if en - st >= a["min_segment"]:
            sl = slice(i, j + 1)
            # スコア: ゆっくり一定速度で動いているほど高い(完全静止より「ゆっくり動く」を好む)
            sp = float(speed[sl].mean())
            steadiness = 1.0 - min(1.0, float(shake[sl].mean()) / a["max_shake"])
            glide = float(np.exp(-((sp - a["ideal_speed"]) ** 2) / (2 * a["ideal_speed_width"] ** 2)))
            sharpness = min(1.0, float(sharp_ratio[sl].mean()))
            score = 0.45 * steadiness + 0.35 * glide + 0.20 * sharpness
            segs.extend(_split_long(a, Segment(
                clip=path, start=round(float(st), 2), end=round(float(en), 2), fps=fps,
                width=W, height=H, score=round(score, 3), speed=round(sp, 4),
                direction=(float(sx[sl].mean()), float(sy[sl].mean()), float(sz[sl].mean())),
            )))
        i = j + 1

    debug = dict(t=t.tolist(), speed=speed.tolist(), shake=shake.tolist(),
                 sharp_ratio=sharp_ratio.tolist(), good=good.tolist(), fps=fps,
                 duration=pr.duration, portrait=pr.portrait)
    return segs, debug


def _split_long(a: dict, seg: Segment) -> list[Segment]:
    """長回しの1カット(家中を歩いて撮った素材など)は、部屋ごとに判定できるよう数秒単位に分割する。"""
    max_len, target = a.get("split_max", 6.5), a.get("split_target", 5.0)
    if seg.duration <= max_len:
        return [seg]
    k = int(np.ceil(seg.duration / target))
    L = seg.duration / k
    out = []
    for m in range(k):
        s = Segment(**{**seg.__dict__})
        s.start = round(seg.start + m * L, 2)
        s.end = round(seg.start + (m + 1) * L, 2)
        out.append(s)
    return out


def analyze_all(paths: list[str], cfg: dict, log=print) -> tuple[list[Segment], dict]:
    all_segs, debug = [], {}
    for p in paths:
        segs, dbg = analyze_clip(p, cfg)
        for k, s in enumerate(segs):
            s.id = f"{os.path.splitext(os.path.basename(p))[0]}#{k}"
        used = sum(s.duration for s in segs)
        total = dbg.get("duration", 0.0) if dbg else 0.0
        extra = ""
        if dbg and not dbg.get("portrait", True):
            extra = "  ※横長素材(中央を縦に切り出します・予備扱い)"
        if dbg and dbg.get("fps", 0) < 50:
            extra += f"  ※{dbg['fps']:.0f}fps(スローなし)"
        log(f"  {os.path.basename(p)}: {total:5.1f}秒 → 使える区間 {len(segs)}個 / 計{used:4.1f}秒{extra}")
        all_segs.extend(segs)
        debug[p] = dbg
    return all_segs, debug
