#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_DOUBAO_VOICE = "zh_male_jieshuoxiaoming_uranus_bigtts"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Agent-first wrapper for ppt-narrator with presentation-app-compatible defaults.",
    )
    parser.add_argument("pptx", type=Path, help="Source PPTX.")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output directory.")
    parser.add_argument(
        "--provider",
        choices=["auto", "dry-run", "doubao"],
        default="auto",
        help="Audio provider. auto selects external audio, Doubao when configured, or fails with guidance.",
    )
    parser.add_argument("--audio-input-dir", type=Path, default=None, help="Directory containing page-001.wav/mp3/m4a files.")
    parser.add_argument("--tts-config", type=Path, default=None, help="Optional TTS config JSON.")
    parser.add_argument("--voice", default=DEFAULT_DOUBAO_VOICE, help="Voice identifier for the selected TTS provider.")
    parser.add_argument("--language", default="zh", help="Language hint for TTS.")
    parser.add_argument("--slide-limit", type=int, default=None, help="Process only the first N slides.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing generated outputs.")
    parser.add_argument("--dry-run-if-unconfigured", action="store_true", help="Use dry-run when auto cannot find TTS inputs.")
    args = parser.parse_args()

    provider = _resolve_provider(args)
    if provider is None:
        print(
            "error: no audio source configured. Provide --audio-input-dir, --tts-config, "
            "DOUBAO_TTS_API_KEY, or pass --dry-run-if-unconfigured for a structural test.",
            file=sys.stderr,
        )
        return 2

    runtime_src = _find_runtime_src()
    env = os.environ.copy()
    command = [sys.executable, "-m", "ppt_narrator.cli", str(args.pptx), "--output", str(args.output)]

    if args.audio_input_dir:
        command.extend(["--audio-input-dir", str(args.audio_input_dir)])
    else:
        command.extend(["--provider", provider])
        if provider == "doubao":
            command.extend(
                [
                    "--doubao-voice-mode",
                    "builtin",
                    "--voice",
                    args.voice,
                ]
            )
            if args.tts_config:
                command.extend(["--tts-config", str(args.tts_config)])
        if provider == "dry-run":
            command.extend(["--chars-per-second", "15"])

    command.extend(["--language", args.language, "--write-pptx", "--audio-trigger", "transition-sound"])
    if args.slide_limit is not None:
        command.extend(["--slide-limit", str(args.slide_limit)])
    if args.overwrite:
        command.append("--overwrite")

    cwd = None
    if runtime_src:
        cwd = str(runtime_src.parent.parent)
        env["PYTHONPATH"] = str(runtime_src)

    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode


def _resolve_provider(args: argparse.Namespace) -> str | None:
    if args.audio_input_dir:
        return "external"
    if args.provider != "auto":
        return args.provider
    if args.tts_config or os.getenv("PPT_NARRATOR_TTS_CONFIG") or os.getenv("DOUBAO_TTS_API_KEY"):
        return "doubao"
    if args.dry_run_if_unconfigured:
        return "dry-run"
    return None


def _find_runtime_src() -> Path | None:
    env_root = os.getenv("PPT_NARRATOR_REPO", "").strip()
    candidates: list[Path] = []
    if env_root:
        root = Path(env_root).expanduser().resolve()
        candidates.extend([root / "src", root / "runtime" / "src"])
    script_path = Path(__file__).resolve()
    for parent in script_path.parents:
        candidates.extend([parent / "runtime" / "src", parent / "src"])
    for candidate in candidates:
        if (candidate / "ppt_narrator").is_dir():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
