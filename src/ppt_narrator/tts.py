from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio import DEFAULT_SAMPLE_RATE, estimate_duration_seconds, probe_audio_duration, write_silence_wav


DOUBAO_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DOUBAO_RESOURCE_ID = "seed-tts-2.0"
DOUBAO_CLONE_RESOURCE_ID = "seed-icl-2.0"
DOUBAO_DEFAULT_SPEAKER = "zh_male_jieshuoxiaoming_uranus_bigtts"


@dataclass(frozen=True)
class DryRunTTSProvider:
    chars_per_second: float

    def synthesize(self, text: str, output_path: Path, voice: str) -> dict:
        duration = estimate_duration_seconds(text, self.chars_per_second)
        write_silence_wav(output_path, duration)
        return {
            "slide_index": _slide_index_from_path(output_path),
            "provider": "dry-run",
            "voice": voice,
            "path": str(output_path),
            "duration_seconds": round(duration, 3),
        }


@dataclass(frozen=True)
class DoubaoTTSProvider:
    endpoint: str
    api_key: str
    resource_id: str
    speaker: str
    voice_mode: str
    language: str
    audio_format: str
    sample_rate: int
    timeout_seconds: float

    def synthesize(self, text: str, output_path: Path, voice: str) -> dict:
        slide_index = _slide_index_from_path(output_path)
        if not text.strip():
            write_silence_wav(output_path, 0.0, sample_rate=self.sample_rate)
            return {
                "slide_index": slide_index,
                "provider": "doubao",
                "voice": self.speaker,
                "path": str(output_path),
                "duration_seconds": 0.0,
                "skipped": "empty_text",
            }

        if not self.api_key:
            raise RuntimeError("doubao provider requires DOUBAO_TTS_API_KEY or a config api_key")
        if _requires_doubao_speaker(self.resource_id) and not self.speaker:
            raise RuntimeError("doubao clone voice requires --voice, DOUBAO_TTS_SPEAKER_ID, or config speaker_id")

        request_id = str(uuid.uuid4())
        payload = {
            "request_id": request_id,
            "req_params": {
                "text": text,
                "audio_params": {
                    "format": self.audio_format,
                    "sample_rate": self.sample_rate,
                },
            },
        }
        if self.speaker:
            payload["req_params"]["speaker"] = self.speaker
        if self.language:
            payload["req_params"]["language"] = self.language

        request = urllib.request.Request(
            url=self.endpoint,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/octet-stream",
                "X-Api-Key": self.api_key,
                "X-Api-Resource-Id": self.resource_id,
                "X-Api-Request-Id": request_id,
            },
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = (response.headers.get("Content-Type") or "").lower()
                if "application/json" in content_type or "text/plain" in content_type:
                    audio_bytes = _decode_doubao_json_audio(response.read().decode("utf-8", errors="ignore"))
                    output_path.write_bytes(audio_bytes)
                else:
                    _write_response_body(response, output_path)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"doubao TTS request failed: HTTP {exc.code}, body={body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"doubao TTS request failed: {exc}") from exc

        if output_path.stat().st_size <= 0:
            raise RuntimeError("doubao TTS returned empty audio")

        return {
            "slide_index": slide_index,
            "provider": "doubao",
            "voice": self.speaker,
            "path": str(output_path),
            "duration_seconds": probe_audio_duration(output_path),
            "resource_id": self.resource_id,
            "voice_mode": self.voice_mode,
            "request_id": request_id,
        }


def build_tts_provider(
    name: str,
    chars_per_second: float,
    voice: str = "",
    config_path: Path | None = None,
    language: str = "zh",
    doubao_resource_id: str = "",
    doubao_voice_mode: str = "builtin",
) -> DryRunTTSProvider | DoubaoTTSProvider:
    if name == "dry-run":
        return DryRunTTSProvider(chars_per_second=chars_per_second)
    if name == "doubao":
        config = _load_doubao_config(config_path)
        if doubao_voice_mode not in {"builtin", "clone", "config"}:
            raise ValueError(f"unsupported doubao voice mode: {doubao_voice_mode}")
        resource_id = _resolve_doubao_resource_id(config, doubao_resource_id, doubao_voice_mode)
        speaker = _resolve_doubao_speaker(config, voice, doubao_voice_mode)
        return DoubaoTTSProvider(
            endpoint=_pick(config, "endpoint", env="DOUBAO_TTS_ENDPOINT", default=DOUBAO_ENDPOINT),
            api_key=_pick(config, "api_key", env="DOUBAO_TTS_API_KEY"),
            resource_id=resource_id,
            speaker=speaker,
            voice_mode=doubao_voice_mode,
            language=language,
            audio_format=_pick(config, "format", "audio_format", default="wav"),
            sample_rate=_coerce_int(_pick(config, "sample_rate", default=str(DEFAULT_SAMPLE_RATE)), DEFAULT_SAMPLE_RATE),
            timeout_seconds=_coerce_float(_pick(config, "timeout_seconds", "timeout_s", env="DOUBAO_TTS_TIMEOUT_S", default="60"), 60.0),
        )
    raise ValueError(f"Unsupported provider in MVP: {name}")


def _resolve_doubao_resource_id(config: dict[str, Any], explicit_resource_id: str, voice_mode: str) -> str:
    explicit = explicit_resource_id.strip()
    if explicit:
        return explicit
    normalized_mode = voice_mode.strip().lower()
    if normalized_mode == "builtin":
        return DOUBAO_RESOURCE_ID
    if normalized_mode == "clone":
        return DOUBAO_CLONE_RESOURCE_ID
    return _pick(config, "resource_id", env="DOUBAO_TTS_RESOURCE_ID", default=DOUBAO_RESOURCE_ID)


def _resolve_doubao_speaker(config: dict[str, Any], voice: str, voice_mode: str) -> str:
    explicit_voice = voice.strip() if voice and voice != "dry-run" else ""
    if explicit_voice:
        return explicit_voice
    normalized_mode = voice_mode.strip().lower()
    if normalized_mode == "builtin":
        return DOUBAO_DEFAULT_SPEAKER
    return _pick(config, "speaker_id", "speaker", "voice_type", env="DOUBAO_TTS_SPEAKER_ID")


def _requires_doubao_speaker(resource_id: str) -> bool:
    return resource_id.strip().lower() == DOUBAO_CLONE_RESOURCE_ID


def _slide_index_from_path(path: Path) -> int:
    stem = path.stem
    try:
        return int(stem.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def _load_doubao_config(config_path: Path | None) -> dict[str, Any]:
    paths = []
    if config_path:
        paths.append(config_path.expanduser())
    env_path = os.getenv("PPT_NARRATOR_TTS_CONFIG", "").strip()
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(Path("volcengine.local.json"))
    paths.append(Path("/Users/ek0kies/Documents/Projects/Work/AiVideoClip/studio_v2/config.cloud.local.json"))

    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        config = _extract_doubao_config(payload)
        if config:
            return config
    return {}


def _extract_doubao_config(payload: dict[str, Any]) -> dict[str, Any]:
    # Supports both ai-video-editor volcengine.local.json and Studio V2 config.cloud.local.json shapes.
    candidates = [
        payload.get("tts"),
        (payload.get("production") or {}).get("tts") if isinstance(payload.get("production"), dict) else None,
    ]
    credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        output = dict(candidate)
        if credentials:
            output.setdefault("api_key", credentials.get("api_key", ""))
            output.setdefault("app_id", credentials.get("app_id", ""))
            output.setdefault("access_token", credentials.get("access_token", ""))
        return {key: value for key, value in output.items() if value not in (None, "")}
    return {}


def _pick(config: dict[str, Any], *keys: str, env: str = "", default: str = "") -> str:
    for key in keys:
        value = str(config.get(key, "")).strip()
        if value and not value.startswith("replace-with-"):
            return value
    if env:
        value = os.getenv(env, "").strip()
        if value:
            return value
    return default


def _coerce_int(value: str, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _decode_doubao_json_audio(raw: str) -> bytes:
    decoder = json.JSONDecoder()
    index = 0
    chunks = []
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw):
            break
        obj, end = decoder.raw_decode(raw, index)
        index = end
        if not isinstance(obj, dict):
            continue
        code = obj.get("code")
        if code not in {None, 0, "0", 20000000, "20000000"}:
            raise RuntimeError(f"doubao TTS business error: code={code}, message={obj.get('message')}")
        data = obj.get("data")
        if isinstance(data, str) and data:
            chunks.append(base64.b64decode(data))
    if not chunks:
        raise RuntimeError("doubao TTS returned JSON but no audio payload")
    return b"".join(chunks)


def _write_response_body(response: Any, output_path: Path) -> None:
    with output_path.open("wb") as handle:
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            handle.write(chunk)

