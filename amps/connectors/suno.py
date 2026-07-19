"""AMPS connectors: Suno音源生成（Phase2オプション）。

Suno公式は開発者向けAPIを一般公開していないため、ここでは第三者Suno APIプロバイダーの
**EvoLink（https://evolink.ai/suno）を想定**したクライアントにしている
（99.9%稼働率SLA・自動フェイルオーバーがあり、無人稼働するAMPSのパイプライン向けとして選定）。
別プロバイダーに乗り換える場合は `_submit_generation` / `_poll_result` のエンドポイント・
レスポンス項目名を、契約したプロバイダーのドキュメントに合わせて調整すること。

## 安全装置（重要）
`config.SUNO_MONTHLY_GENERATION_CAP` を超えたら、プロバイダー側の課金設定に関わらず
**このコードが呼び出し自体をブロックする**（SunoQuotaExceeded）。
これにより「気づいたら上限を超えて課金されていた」を防ぐ。

使い方:
    from connectors import suno
    result = suno.generate_song(song_id, style_prompt, formatted_lyrics, title)
    # result["audio_local_path"] に保存された音源ファイルのパスが入る
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import db  # noqa: E402

POLL_INTERVAL_SEC = 10
POLL_TIMEOUT_SEC = 300  # 5分でタイムアウト


class SunoNotConfigured(RuntimeError):
    pass


class SunoQuotaExceeded(RuntimeError):
    pass


class SunoGenerationError(RuntimeError):
    pass


def remaining_quota() -> int:
    used = db.count_suno_generations_this_month()
    return max(0, config.SUNO_MONTHLY_GENERATION_CAP - used)


def _check_quota(song_id: Optional[int]) -> None:
    used = db.count_suno_generations_this_month()
    if used >= config.SUNO_MONTHLY_GENERATION_CAP:
        db.log_suno_generation(song_id, status="quota_blocked",
                                error=f"monthly cap reached ({used}/{config.SUNO_MONTHLY_GENERATION_CAP})")
        raise SunoQuotaExceeded(
            f"月間生成上限（{config.SUNO_MONTHLY_GENERATION_CAP}回）に達しています。"
            f"config.SUNO_MONTHLY_GENERATION_CAP（.envのSUNO_MONTHLY_GENERATION_CAP）で調整できます。"
        )


def _headers() -> dict:
    if not config.SUNO_API_KEY:
        raise SunoNotConfigured(
            "SUNO_API_KEY が未設定です。.env に設定してください（.env.example 参照）。"
        )
    return {"Authorization": f"Bearer {config.SUNO_API_KEY}", "Content-Type": "application/json"}


def _extract_style_summary(style_prompt: str, max_len: int = 900) -> str:
    """suno_prompt.md の Style Prompt 部分をAPI送信用に整形（長すぎる場合は切り詰める）。"""
    text = style_prompt.strip()
    return text[:max_len]


def _submit_generation(style_prompt: str, formatted_lyrics: str, title: str) -> str:
    """EvoLink: POST /v1/audios/generations → {"id": "task-xxx", "status": "pending", ...}"""
    payload = {
        "model": config.SUNO_MODEL,
        "prompt": formatted_lyrics,
        "style": _extract_style_summary(style_prompt),
        "title": title[:80],
        "custom_mode": True,
        "instrumental": False,
    }
    resp = requests.post(f"{config.SUNO_API_BASE_URL}/v1/audios/generations",
                          json=payload, headers=_headers(), timeout=30)
    if resp.status_code != 200:
        raise SunoGenerationError(f"generate request failed: {resp.status_code} {resp.text[:500]}")
    data = resp.json()
    task_id = data.get("id") or data.get("task_id")
    if not task_id:
        raise SunoGenerationError(f"task id not found in response: {data}")
    return task_id


def _poll_result(task_id: str) -> dict:
    """EvoLink: GET /v1/tasks/{task_id} → completed時 result_data[0].audio_url を取得。"""
    deadline = time.time() + POLL_TIMEOUT_SEC
    while time.time() < deadline:
        resp = requests.get(f"{config.SUNO_API_BASE_URL}/v1/tasks/{task_id}",
                             headers=_headers(), timeout=30)
        if resp.status_code != 200:
            raise SunoGenerationError(f"poll request failed: {resp.status_code} {resp.text[:500]}")
        data = resp.json()
        status = str(data.get("status", "")).lower()
        if status in ("completed", "success", "succeeded"):
            results = data.get("result_data") or data.get("results") or []
            if not results:
                raise SunoGenerationError(f"no results in completed response: {data}")
            audio_url = results[0].get("audio_url") or results[0].get("audioUrl")
            if not audio_url:
                raise SunoGenerationError(f"audio_url not found in result: {results[0]}")
            return {"audio_url": audio_url, "raw": data}
        if status in ("failed", "error"):
            raise SunoGenerationError(f"generation failed on provider side: {data}")
        time.sleep(POLL_INTERVAL_SEC)
    raise SunoGenerationError(f"polling timed out after {POLL_TIMEOUT_SEC}s (task_id={task_id})")


def _download_audio(audio_url: str, dest_path: Path) -> None:
    resp = requests.get(audio_url, timeout=60)
    if resp.status_code != 200:
        raise SunoGenerationError(f"audio download failed: {resp.status_code}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(resp.content)


def generate_song(song_id: int, style_prompt: str, formatted_lyrics: str, title: str) -> dict:
    """Suno APIで音源を生成し、songs/配下に保存する。月間上限を超えていたら実行前にブロックする。"""
    _check_quota(song_id)

    gen_id = db.log_suno_generation(song_id, status="requested")
    try:
        task_id = _submit_generation(style_prompt, formatted_lyrics, title)
        db.update_suno_generation(gen_id, status="requested", task_id=task_id)

        result = _poll_result(task_id)
        audio_url = result["audio_url"]

        import pipeline  # 遅延importで循環参照を避ける
        n_existing = len(db.list_suno_generations(song_id))
        dest = pipeline.song_dir(song_id) / f"audio_v{n_existing}.mp3"
        _download_audio(audio_url, dest)

        db.update_suno_generation(gen_id, status="done", audio_url=audio_url,
                                   audio_local_path=str(dest))
        return {"audio_url": audio_url, "audio_local_path": str(dest), "task_id": task_id}
    except Exception as exc:  # noqa: BLE001
        db.update_suno_generation(gen_id, status="failed", error=str(exc)[:1000])
        raise
