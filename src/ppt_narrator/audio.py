from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path


DEFAULT_SAMPLE_RATE = 16_000


def write_silence_wav(path: Path, duration_seconds: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
    """Write a mono 16-bit PCM WAV file used by the dry-run provider."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(duration_seconds * sample_rate))
    silence_frame = b"\x00\x00"

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(silence_frame * frame_count)


def estimate_duration_seconds(text: str, chars_per_second: float) -> float:
    """Estimate narration duration for dry-run timing assets."""
    normalized_length = len("".join(text.split()))
    if normalized_length == 0:
        return 0.0
    return max(2.0, normalized_length / chars_per_second)


def probe_audio_duration(path: Path) -> float | None:
    """Return audio duration in seconds using ffprobe first, then WAV metadata."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                duration = json.loads(result.stdout).get("format", {}).get("duration")
                if duration is not None:
                    return round(float(duration), 3)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate <= 0:
                return None
            return round(frames / float(rate), 3)
    except Exception:
        return None
