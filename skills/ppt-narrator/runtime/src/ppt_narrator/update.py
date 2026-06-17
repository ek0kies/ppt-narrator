from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio import probe_audio_duration
from .pipeline import build_manifest, render_notes_markdown
from .pptx_notes import SlideNotes, extract_slide_notes
from .pptx_writer import SlideAudio, write_auto_advance_pptx
from .tts import build_tts_provider


DEFAULT_UPDATE_DIR_NAME = "updated"


@dataclass(frozen=True)
class UpdateOptions:
    manifest_path: Path
    request_path: Path
    output_dir: Path | None
    provider: str = "auto"
    voice: str = "dry-run"
    language: str = "zh"
    tts_config: Path | None = None
    audio_input_dir: Path | None = None
    doubao_resource_id: str = ""
    doubao_voice_mode: str = "builtin"
    chars_per_second: float = 15.0
    overwrite: bool = False
    write_pptx: bool = True
    pptx_output: Path | None = None
    advance_padding_ms: int = 500
    pptx_audio_format: str = "source"
    visible_audio_icon: bool = False
    direct_audio_start: bool = False
    audio_trigger: str = "transition-sound"
    dry_run_if_unconfigured: bool = False


@dataclass(frozen=True)
class UpdateResult:
    output_dir: Path
    notes_markdown: Path
    manifest_json: Path
    audio_dir: Path | None
    narrated_pptx: Path | None
    slide_count: int
    updated_slide_indexes: list[int]


@dataclass(frozen=True)
class _SlideUpdate:
    text: str | None = None
    voice: str | None = None
    audio_path: Path | None = None
    regenerate_audio: bool = False


def run_update(options: UpdateOptions) -> UpdateResult:
    """Apply a structured conversation update to a previous narration output."""
    manifest_path = options.manifest_path.expanduser().resolve()
    request_path = options.request_path.expanduser().resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"Previous manifest does not exist: {manifest_path}")
    if not request_path.exists():
        raise FileNotFoundError(f"Update request does not exist: {request_path}")
    if options.chars_per_second <= 0:
        raise ValueError("--chars-per-second must be greater than 0")

    previous_manifest = _load_json_object(manifest_path)
    update_request = _load_json_object(request_path)
    input_value = str(previous_manifest.get("input", "")).strip()
    if not input_value:
        raise ValueError("Previous manifest is missing input")
    input_pptx = Path(input_value).expanduser().resolve()
    if not input_pptx.exists():
        raise FileNotFoundError(f"Source PPTX from previous manifest does not exist: {input_pptx}")
    if input_pptx.suffix.lower() != ".pptx":
        raise ValueError(f"Previous manifest input is not a .pptx file: {input_pptx}")

    output_dir = (
        options.output_dir.expanduser().resolve()
        if options.output_dir
        else manifest_path.parent / DEFAULT_UPDATE_DIR_NAME
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    notes_markdown = output_dir / "notes.md"
    manifest_json = output_dir / "manifest.json"
    narrated_pptx = (
        options.pptx_output.expanduser().resolve()
        if options.pptx_output
        else output_dir / f"{input_pptx.stem}.auto-narrated.pptx"
    ) if options.write_pptx else None
    audio_dir = output_dir / "audio"

    planned_outputs = [notes_markdown, manifest_json]
    if narrated_pptx:
        planned_outputs.append(narrated_pptx)
    for output_path in planned_outputs:
        _ensure_writable(output_path, options.overwrite)

    previous_slides = _load_previous_slides(input_pptx, manifest_path, previous_manifest)
    updates = _parse_update_request(update_request, previous_slides)
    slides = _apply_text_updates(previous_slides, updates)
    audio_entries = _build_audio_entries(options, previous_manifest, slides, updates, audio_dir)

    if narrated_pptx:
        if not audio_entries:
            raise RuntimeError("writing an updated PPTX requires audio entries")
        write_auto_advance_pptx(
            input_pptx=input_pptx,
            output_pptx=narrated_pptx,
            slide_audio=[
                SlideAudio(
                    slide_index=entry["slide_index"],
                    audio_path=Path(entry["path"]),
                    duration_seconds=float(entry.get("duration_seconds") or 0.0),
                )
                for entry in audio_entries
            ],
            advance_padding_ms=options.advance_padding_ms,
            embed_audio_format=options.pptx_audio_format,
            visible_audio_icon=options.visible_audio_icon,
            direct_audio_start=options.direct_audio_start,
            audio_trigger=options.audio_trigger,
        )

    notes_markdown.write_text(render_notes_markdown(input_pptx, slides), encoding="utf-8")
    manifest_json.write_text(
        json.dumps(build_manifest(input_pptx, slides, audio_entries, narrated_pptx), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return UpdateResult(
        output_dir=output_dir,
        notes_markdown=notes_markdown,
        manifest_json=manifest_json,
        audio_dir=audio_dir if audio_dir.exists() else None,
        narrated_pptx=narrated_pptx,
        slide_count=len(slides),
        updated_slide_indexes=sorted(updates),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ppt-narrator-update",
        description="Apply a structured conversation update to a previous ppt-narrator manifest.",
    )
    parser.add_argument("--manifest", type=Path, required=True, help="Previous manifest.json.")
    parser.add_argument("--request", type=Path, required=True, help="Structured update request JSON.")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output directory for the updated result.")
    parser.add_argument("--provider", choices=["auto", "dry-run", "doubao"], default="auto", help="Audio provider for changed slides.")
    parser.add_argument("--voice", default="dry-run", help="Default voice for changed slides.")
    parser.add_argument("--language", default="zh", help="Language hint passed to the TTS provider.")
    parser.add_argument("--tts-config", type=Path, default=None, help="Optional TTS config JSON.")
    parser.add_argument("--audio-input-dir", type=Path, default=None, help="Optional page-001.wav/mp3/m4a directory for changed slides.")
    parser.add_argument("--doubao-resource-id", default="", help="Override X-Api-Resource-Id for Doubao TTS.")
    parser.add_argument("--doubao-voice-mode", choices=["builtin", "clone", "config"], default="builtin", help="Doubao voice mode.")
    parser.add_argument("--chars-per-second", type=float, default=15.0, help="Dry-run narration speed.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing generated outputs.")
    parser.add_argument("--no-pptx", action="store_true", help="Only write updated notes and manifest.")
    parser.add_argument("--pptx-output", type=Path, default=None, help="Explicit output path for the updated PPTX.")
    parser.add_argument("--advance-padding-ms", type=int, default=500, help="Extra slide time after audio duration.")
    parser.add_argument("--pptx-audio-format", choices=["source", "mp3"], default="source", help="Audio format embedded into PPTX.")
    parser.add_argument("--visible-audio-icon", action="store_true", help="Place visible audio objects on slides.")
    parser.add_argument("--direct-audio-start", action="store_true", help="Start embedded media timing when the slide loads.")
    parser.add_argument("--audio-trigger", choices=["media", "transition-sound"], default="transition-sound", help="How updated PPTX audio is triggered.")
    parser.add_argument("--dry-run-if-unconfigured", action="store_true", help="Use dry-run audio when auto cannot find TTS credentials.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    options = UpdateOptions(
        manifest_path=args.manifest,
        request_path=args.request,
        output_dir=args.output,
        provider=args.provider,
        voice=args.voice,
        language=args.language,
        tts_config=args.tts_config,
        audio_input_dir=args.audio_input_dir,
        doubao_resource_id=args.doubao_resource_id,
        doubao_voice_mode=args.doubao_voice_mode,
        chars_per_second=args.chars_per_second,
        overwrite=args.overwrite,
        write_pptx=not args.no_pptx,
        pptx_output=args.pptx_output,
        advance_padding_ms=args.advance_padding_ms,
        pptx_audio_format=args.pptx_audio_format,
        visible_audio_icon=args.visible_audio_icon,
        direct_audio_start=args.direct_audio_start,
        audio_trigger=args.audio_trigger,
        dry_run_if_unconfigured=args.dry_run_if_unconfigured,
    )
    try:
        result = run_update(options)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"slides: {result.slide_count}")
    print(f"updated_slides: {','.join(str(index) for index in result.updated_slide_indexes)}")
    print(f"notes: {result.notes_markdown}")
    print(f"manifest: {result.manifest_json}")
    if result.audio_dir:
        print(f"audio: {result.audio_dir}")
    if result.narrated_pptx:
        print(f"pptx: {result.narrated_pptx}")
    return 0


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _ensure_writable(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file without --overwrite: {path}")


def _load_previous_slides(input_pptx: Path, manifest_path: Path, manifest: dict[str, Any]) -> list[SlideNotes]:
    manifest_slides = manifest.get("slides")
    if not isinstance(manifest_slides, list):
        raise ValueError("Previous manifest is missing slides[]")

    source_slides = {slide.index: slide for slide in extract_slide_notes(input_pptx)}
    notes_by_slide = _parse_notes_markdown(manifest_path.parent / "notes.md")
    slides: list[SlideNotes] = []
    for item in manifest_slides:
        if not isinstance(item, dict):
            raise ValueError("Previous manifest slides[] items must be objects")
        index = _coerce_positive_int(item.get("index"), "manifest slides[].index")
        source_slide = source_slides.get(index)
        slides.append(
            SlideNotes(
                index=index,
                slide_path=source_slide.slide_path if source_slide else f"ppt/slides/slide{index}.xml",
                notes_path=str(item.get("notes_path") or (source_slide.notes_path if source_slide else "")) or None,
                title=str(item.get("title") or (source_slide.title if source_slide else f"Slide {index}")),
                text=notes_by_slide.get(index, source_slide.text if source_slide else ""),
            )
        )
    return slides


def _parse_notes_markdown(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    notes: dict[int, str] = {}
    current_index: int | None = None
    current_lines: list[str] = []
    heading_pattern = re.compile(r"^## Slide (\d+):")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = heading_pattern.match(line)
        if match:
            if current_index is not None:
                notes[current_index] = _clean_note_text(current_lines)
            current_index = int(match.group(1))
            current_lines = []
            continue
        if current_index is not None:
            current_lines.append(line)
    if current_index is not None:
        notes[current_index] = _clean_note_text(current_lines)
    return notes


def _clean_note_text(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    return "" if text == "_No speaker notes found._" else text


def _parse_update_request(payload: dict[str, Any], slides: list[SlideNotes]) -> dict[int, _SlideUpdate]:
    known_indexes = {slide.index for slide in slides}
    updates: dict[int, _SlideUpdate] = {}
    top_level_targets = _parse_slide_indexes(payload.get("slide_indexes"), known_indexes)
    has_top_level_audio_change = any(key in payload for key in ("voice", "regenerate_audio"))
    if has_top_level_audio_change and not top_level_targets:
        top_level_targets = set(known_indexes)
    for index in sorted(top_level_targets):
        updates[index] = _merge_update(
            updates.get(index),
            _SlideUpdate(
                voice=_optional_text(payload.get("voice")),
                regenerate_audio=bool(payload.get("regenerate_audio", "voice" in payload)),
            ),
        )

    slide_updates = payload.get("slides", [])
    if slide_updates is None:
        slide_updates = []
    if not isinstance(slide_updates, list):
        raise ValueError("update_request.slides must be a list")
    for item in slide_updates:
        if not isinstance(item, dict):
            raise ValueError("Each update_request.slides[] item must be an object")
        index = _coerce_positive_int(item.get("index"), "update_request.slides[].index")
        if index not in known_indexes:
            raise ValueError(f"Update request references unknown slide index: {index}")
        text = item.get("text")
        audio_path = _optional_path(item.get("audio_path"))
        updates[index] = _merge_update(
            updates.get(index),
            _SlideUpdate(
                text=str(text) if text is not None else None,
                voice=_optional_text(item.get("voice")),
                audio_path=audio_path,
                regenerate_audio=bool(item.get("regenerate_audio", text is not None or audio_path is not None or "voice" in item)),
            ),
        )
    if not updates:
        raise ValueError("Update request does not contain any slide text, voice, audio, or regeneration changes")
    return updates


def _parse_slide_indexes(value: Any, known_indexes: set[int]) -> set[int]:
    if value in (None, ""):
        return set()
    raw_values = value if isinstance(value, list) else [value]
    indexes = {_coerce_positive_int(item, "update_request.slide_indexes[]") for item in raw_values}
    unknown = indexes - known_indexes
    if unknown:
        raise ValueError(f"Update request references unknown slide indexes: {sorted(unknown)}")
    return indexes


def _coerce_positive_int(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text).expanduser().resolve() if text else None


def _merge_update(existing: _SlideUpdate | None, incoming: _SlideUpdate) -> _SlideUpdate:
    if existing is None:
        return incoming
    return _SlideUpdate(
        text=incoming.text if incoming.text is not None else existing.text,
        voice=incoming.voice if incoming.voice is not None else existing.voice,
        audio_path=incoming.audio_path if incoming.audio_path is not None else existing.audio_path,
        regenerate_audio=existing.regenerate_audio or incoming.regenerate_audio,
    )


def _apply_text_updates(slides: list[SlideNotes], updates: dict[int, _SlideUpdate]) -> list[SlideNotes]:
    updated_slides: list[SlideNotes] = []
    for slide in slides:
        update = updates.get(slide.index)
        updated_slides.append(
            SlideNotes(
                index=slide.index,
                slide_path=slide.slide_path,
                notes_path=slide.notes_path,
                title=slide.title,
                text=slide.text if update is None or update.text is None else update.text,
            )
        )
    return updated_slides


def _build_audio_entries(
    options: UpdateOptions,
    previous_manifest: dict[str, Any],
    slides: list[SlideNotes],
    updates: dict[int, _SlideUpdate],
    audio_dir: Path,
) -> list[dict[str, Any]]:
    previous_audio = _previous_audio_by_slide(previous_manifest)
    entries: list[dict[str, Any]] = []
    provider_name = _resolve_provider(options, updates)
    providers: dict[str, Any] = {}

    def provider_for(voice: str):
        if provider_name is None:
            return None
        if voice not in providers:
            providers[voice] = build_tts_provider(
                provider_name,
                chars_per_second=options.chars_per_second,
                voice=voice,
                config_path=options.tts_config,
                language=options.language,
                doubao_resource_id=options.doubao_resource_id,
                doubao_voice_mode=options.doubao_voice_mode,
            )
        return providers[voice]

    for slide in slides:
        update = updates.get(slide.index)
        external_audio = _resolve_external_audio(options, slide.index, update)
        if external_audio:
            entries.append(_audio_entry_from_external(slide.index, external_audio))
            continue
        if update and update.regenerate_audio:
            voice = update.voice or options.voice
            provider = provider_for(voice)
            if provider is None:
                raise RuntimeError("No audio source configured for updated slides")
            audio_dir.mkdir(parents=True, exist_ok=True)
            entries.append(provider.synthesize(slide.text, audio_dir / f"page-{slide.index:03d}.wav", voice))
            continue
        previous_entry = previous_audio.get(slide.index)
        if previous_entry and _audio_entry_path_exists(previous_entry):
            entries.append(previous_entry)
            continue
        provider = provider_for(options.voice)
        if provider is None:
            raise RuntimeError(f"Previous audio is missing and no provider is configured for slide {slide.index}")
        audio_dir.mkdir(parents=True, exist_ok=True)
        entries.append(provider.synthesize(slide.text, audio_dir / f"page-{slide.index:03d}.wav", options.voice))
    return entries


def _resolve_provider(options: UpdateOptions, updates: dict[int, _SlideUpdate]) -> str | None:
    if all(update.audio_path for update in updates.values()):
        return None
    if options.provider != "auto":
        return options.provider
    if options.tts_config or os.getenv("PPT_NARRATOR_TTS_CONFIG") or os.getenv("DOUBAO_TTS_API_KEY"):
        return "doubao"
    if options.dry_run_if_unconfigured:
        return "dry-run"
    return None


def _previous_audio_by_slide(manifest: dict[str, Any]) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    slides = manifest.get("slides", [])
    if not isinstance(slides, list):
        return output
    for item in slides:
        if not isinstance(item, dict) or not isinstance(item.get("audio"), dict):
            continue
        index = _coerce_positive_int(item.get("index"), "manifest slides[].index")
        output[index] = dict(item["audio"])
    return output


def _resolve_external_audio(options: UpdateOptions, slide_index: int, update: _SlideUpdate | None) -> Path | None:
    if update and update.audio_path:
        return update.audio_path
    if update is None or not options.audio_input_dir:
        return None
    source_dir = options.audio_input_dir.expanduser().resolve()
    for suffix in (".wav", ".mp3", ".m4a"):
        candidate = source_dir / f"page-{slide_index:03d}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _audio_entry_from_external(slide_index: int, audio_path: Path) -> dict[str, Any]:
    if not audio_path.exists():
        raise FileNotFoundError(f"External audio file does not exist: {audio_path}")
    duration = probe_audio_duration(audio_path)
    if duration is None:
        raise RuntimeError(f"Cannot determine duration for external audio: {audio_path}")
    return {
        "slide_index": slide_index,
        "provider": "external",
        "voice": "external",
        "path": str(audio_path),
        "duration_seconds": duration,
    }


def _audio_entry_path_exists(entry: dict[str, Any]) -> bool:
    path = str(entry.get("path", "")).strip()
    return bool(path) and Path(path).expanduser().exists()


if __name__ == "__main__":
    raise SystemExit(main())
