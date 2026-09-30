"""書き出し: カットを縦型キャンバスに配置し、ゆっくり寄り(Ken Burns)・上品なトランジション・テロップを合成して mp4 にする。

フレーム単位で Python(OpenCV/numpy)で合成し、ffmpeg にパイプして H.264 でエンコードする。
ffmpeg のフィルタだけで組むより、サブピクセル精度の滑らかなズームやぼかしディゾルブが作りやすい。
"""
from __future__ import annotations

import math
import os
import subprocess

import cv2
import numpy as np

from .planner import Shot
from .telop import Layer, build_telop


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


class ShotSource:
    """1カット分のフレームを ffmpeg で正確な位置からデコードして順に供給する。"""

    def __init__(self, shot: Shot, W: int, H: int, margin: float = 1.08):
        self.shot, self.W, self.H = shot, W, H
        self.cw = int(math.ceil(W * margin / 2) * 2)
        self.ch = int(math.ceil(H * margin / 2) * 2)
        self.proc = None
        self.idx = -1
        self.frame = None
        self.static = None
        if shot.image:
            img = cv2.imdecode(np.fromfile(shot.image, dtype=np.uint8), cv2.IMREAD_COLOR)  # 日本語パス対策
            if img is None:
                raise FileNotFoundError(f"広告画像を読めません: {shot.image}")
            self.static = self._cover(img)
        else:
            # 30fps素材をスローにするときは、60fpsの中間コマを作ってからデコードする
            self.fps = 60.0 if shot.interp else shot.seg.fps

    def _cover(self, img):
        """縦長キャンバスを埋めるよう拡大し、はみ出た分を中央で切る(横長素材はここで中央切り出し=予備)。"""
        h, w = img.shape[:2]
        s = max(self.cw / w, self.ch / h)
        img = cv2.resize(img, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_LANCZOS4)
        y0 = (img.shape[0] - self.ch) // 2
        x0 = (img.shape[1] - self.cw) // 2
        return img[y0:y0 + self.ch, x0:x0 + self.cw]

    def _open(self):
        sh = self.shot
        length = sh.duration * sh.speed + 0.5
        vf = (f"scale={self.cw}:{self.ch}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={self.cw}:{self.ch}")
        if sh.interp == "blend":
            vf += ",framerate=fps=60"
        elif sh.interp == "flow":
            vf += ",minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{sh.src_start:.3f}", "-i", sh.seg.clip, "-t", f"{length:.3f}",
               "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8)

    def get(self, u: float):
        """カット内のローカル時刻 u(秒)のフレーム(cw x ch)を返す。"""
        if self.static is not None:
            return self.static
        if self.proc is None:
            self._open()
        want = int(u * self.shot.speed * self.fps + 1e-6)
        n = self.cw * self.ch * 3
        while self.idx < want:
            buf = self.proc.stdout.read(n)
            if len(buf) < n:
                break  # 素材末尾: 最後のフレームを保持
            self.frame = np.frombuffer(buf, np.uint8).reshape(self.ch, self.cw, 3)
            self.idx += 1
        return self.frame

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc = None


def _zoomed(src, W, H, z):
    """中心基準で倍率 z に寄った W x H の画像(サブピクセル補間で滑らか)。"""
    ch, cw = src.shape[:2]
    # src(cw x ch)の中心を出力中心に合わせ、z倍する
    M = np.array([[z, 0, W / 2 - z * cw / 2], [0, z, H / 2 - z * ch / 2]], dtype=np.float32)
    # margin ぶん大きい素材なので z>=1/margin なら端は出ない
    return cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _blur(img, amount):
    if amount < 0.02:
        return img
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    k = 1 + 2 * int(amount * 12)
    small = cv2.GaussianBlur(small, (k, k), 0)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _zoom_img(img, z, blur=0.0):
    h, w = img.shape[:2]
    M = np.array([[z, 0, w / 2 - z * w / 2], [0, z, h / 2 - z * h / 2]], dtype=np.float32)
    out = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return _blur(out, blur) if blur else out


_warm_cache = {}


def _transition(a, b, kind, p):
    """トランジション。どれも派手さを抑え、ゆっくりなじませる。
    dissolve       クロスディゾルブ
    blur_dissolve  中間でふわっとぼける
    light_leak     暖かい光がふわっと差し込み、その光の中で切り替わる
    zoom_through   前のカットに少し寄りながらぼけ、次のカットが少し引いた状態から現れる
    soft_wipe      境界をぼかした光の帯が左から右へ流れて切り替わる(カメラの横移動と相性が良い)
    dip_black      一瞬だけ暗くなって切り替わる(章の区切り)
    fade_white     白くなって切り替わる(広告の前後)
    cut            そのまま切り替える(動きつなぎ)
    """
    e = _ease(p)
    if kind == "blur_dissolve":
        amt = math.sin(math.pi * p)          # 中間で最大にぼける
        a2, b2 = _blur(a, amt), _blur(b, amt)
        return cv2.addWeighted(a2, 1 - e, b2, e, 0)
    if kind in ("fade_white", "fade_black", "dip_black"):
        c = np.full_like(a, 255 if kind == "fade_white" else 0)
        if kind == "dip_black":            # 真っ黒にはしない(7割まで)
            k = math.sin(math.pi * p) * 0.75
            mix = cv2.addWeighted(a, 1 - e, b, e, 0)
            return cv2.addWeighted(mix, 1 - k, c, k, 0)
        if p < 0.5:
            return cv2.addWeighted(a, 1 - _ease(p * 2), c, _ease(p * 2), 0)
        return cv2.addWeighted(c, 1 - _ease(p * 2 - 1), b, _ease(p * 2 - 1), 0)
    if kind == "light_leak":
        mix = cv2.addWeighted(a, 1 - e, b, e, 0).astype(np.float32)
        h, w = a.shape[:2]
        key = (h, w)
        if key not in _warm_cache:        # 右上から差し込む暖色の光(やわらかいグラデーション)
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            d = np.hypot((xx - w * 0.85) / w, (yy - h * 0.15) / h)
            g = np.clip(1.0 - d / 0.9, 0, 1) ** 1.6
            _warm_cache[key] = np.dstack([g * 170, g * 225, g * 255]).astype(np.float32)  # BGR(暖色)
        k = math.sin(math.pi * p) ** 1.5
        glow = _warm_cache[key] * k
        out = 255 - (255 - mix) * (255 - glow) / 255   # スクリーン合成
        return np.clip(out, 0, 255).astype(np.uint8)
    if kind == "zoom_through":
        za = 1.0 + 0.12 * _ease(p)
        zb = 1.12 - 0.12 * _ease(p)
        amt = math.sin(math.pi * p) * 0.6
        return cv2.addWeighted(_zoom_img(a, za, amt), 1 - e, _zoom_img(b, zb, amt), e, 0)
    if kind == "soft_wipe":
        h, w = a.shape[:2]
        feather = 0.45
        x = np.linspace(0, 1, w, dtype=np.float32)
        pos = -feather + (1 + 2 * feather) * e
        m = np.clip((pos - x) / feather + 0.5, 0, 1)
        m = m * m * (3 - 2 * m)
        m3 = np.repeat(m[None, :, None], h, 0)
        out = a.astype(np.float32) * (1 - m3) + b.astype(np.float32) * m3
        band = np.exp(-((x - pos) / (feather * 0.35)) ** 2) * 0.35 * math.sin(math.pi * p)  # 境目にうっすら光
        out = 255 - (255 - out) * (1 - band[None, :, None])
        return np.clip(out, 0, 255).astype(np.uint8)
    if kind == "cut":
        return a if p < 0.5 else b
    return cv2.addWeighted(a, 1 - e, b, e, 0)  # dissolve


TRANSITION_NAMES = {
    "blur_dissolve": "ぼかしディゾルブ(現行)", "dissolve": "クロスディゾルブ", "light_leak": "ライトリーク(光が差し込む)",
    "zoom_through": "ズームスルー(寄って抜ける)", "soft_wipe": "ソフトワイプ(光の帯が流れる)", "dip_black": "ディップ(一瞬暗く)",
    "cut": "カット(動きつなぎ)",
}


def _composite(frame: np.ndarray, layer: Layer, alpha: float, dx: float, dy: float):
    if alpha <= 0.001:
        return
    img = layer.img
    h, w = img.shape[:2]
    x = int(round(layer.x + dx)); y = int(round(layer.y + dy))
    H, W = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sub = img[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sub[..., 3:4] * alpha
    rgb = sub[..., 2::-1] * 255.0  # RGBA(Pillow) → BGR
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (roi * (1 - a) + rgb * a).astype(np.uint8)


def timeline(plan: list[Shot]):
    starts, t = [], 0.0
    for i, s in enumerate(plan):
        if i > 0:
            t -= s.transition_in.get("duration", 0.0)
        starts.append(t)
        t += s.duration
    return starts, t


def render(plan: list[Shot], cfg: dict, fonts: dict, props: dict, copy: dict, out_path: str,
           bgm: str | None = None, log=print):
    W, H, fps = cfg["canvas"]["width"], cfg["canvas"]["height"], cfg["canvas"]["fps"]
    z0, z1 = cfg["motion"]["push_in"]
    starts, total = timeline(plan)
    nframes = int(round(total * fps))

    # テロップの表示区間を決める
    telops = []  # (t_start, t_end, [Layer])
    for i, s in enumerate(plan):
        if not s.telop:
            continue
        last = min(len(plan) - 1, i + s.telop_span - 1)
        # 前のトランジションの中間から出す(白フェード・ぼかしの最中に文字が埋もれないように)
        t0 = starts[i] + s.transition_in.get("duration", 0.0) * 0.5
        t1 = starts[last] + plan[last].duration
        if last + 1 < len(plan):  # 次のトランジションの中間で消えるように
            t1 = starts[last + 1] + plan[last + 1].transition_in.get("duration", 0) * 0.5
        layers = build_telop(s.telop, cfg, fonts, props, copy, room=s.room)
        telops.append((t0, t1, layers))

    sources = [ShotSource(s, W, H) for s in plan]
    tmp_video = out_path if not bgm else out_path + ".video.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", tmp_video], stdin=subprocess.PIPE)

    def shot_frame(i, t):
        s = plan[i]
        u = t - starts[i]
        src = sources[i].get(max(0.0, u))
        prog = u / s.duration if s.duration else 0
        if s.image:
            z = 1.0 + cfg["motion"].get("ad_zoom", 0.0) * prog
        else:
            z = z0 + (z1 - z0) * prog
        return _zoomed(src, W, H, z / sources[i].cw * W)  # 素材は1.08倍の余白付きでデコードしている

    end_fade = cfg["transitions"].get("ending_fade", 0.0)
    for fi in range(nframes):
        t = fi / fps
        active = [i for i in range(len(plan)) if starts[i] <= t < starts[i] + plan[i].duration]
        if not active:
            active = [len(plan) - 1]
        if len(active) == 1:
            frame = shot_frame(active[0], t)
        else:
            a_i, b_i = active[0], active[-1]
            tr = plan[b_i].transition_in
            p = (t - starts[b_i]) / tr["duration"] if tr.get("duration") else 1.0
            frame = _transition(shot_frame(a_i, t), shot_frame(b_i, t), tr.get("type", "dissolve"), p)
        frame = np.ascontiguousarray(frame)
        for (t0, t1, layers) in telops:
            if t0 <= t < t1:
                for L in layers:
                    al, dx, dy = L.anim(t - t0, t1 - t0)
                    _composite(frame, L, al, dx, dy)
        if end_fade and t > total - end_fade:
            k = _ease((total - t) / end_fade)
            frame = (frame.astype(np.float32) * k).astype(np.uint8)
        enc.stdin.write(frame.tobytes())
        # 使い終わったカットのデコーダを閉じる
        for i in range(len(plan)):
            if sources[i].proc and t > starts[i] + plan[i].duration + 0.1:
                sources[i].close()
        if fi % (fps * 5) == 0:
            log(f"  書き出し中 {t:5.1f} / {total:.1f}秒")
    enc.stdin.close()
    enc.wait()
    for s in sources:
        s.close()

    if bgm:
        fo = max(0.0, total - 1.5)
        # BGM が動画より短いときはループ、長いときは動画の尺で切り、最後の1.5秒でフェードアウト
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp_video, "-stream_loop", "-1", "-i", bgm,
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-af", f"afade=t=in:d=0.3,afade=t=out:st={fo:.2f}:d=1.5", "-t", f"{total:.3f}",
                        "-movflags", "+faststart", out_path], check=True)
        os.remove(tmp_video)
    log(f"  完了: {out_path}  ({total:.1f}秒, {nframes}フレーム)")
    return total
