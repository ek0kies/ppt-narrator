from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .audio import probe_audio_duration
from .pptx_notes import SlideNotes, extract_slide_notes
from .pptx_writer import SlideAudio, write_auto_advance_pptx
from .tts import build_tts_provider


@dataclass(frozen=True)
class NarrationOptions:
    input_pptx: Path
    output_dir: Path | None
    provider: str = "dry-run"
    voice: str = "dry-run"
    language: str = "zh"
    tts_config: Path | None = None
    audio_input_dir: Path | None = None
    doubao_resource_id: str = ""
    doubao_voice_mode: str = "builtin"
    chars_per_second: float = 15.0
    audio_enabled: bool = True
    overwrite: bool = False
    slide_limit: int | None = None
    write_pptx: bool = False
    pptx_output: Path | None = None
    advance_padding_ms: int = 500
    pptx_audio_format: str = "source"
    visible_audio_icon: bool = False
    direct_audio_start: bool = False
    audio_trigger: str = "transition-sound"


@dataclass(frozen=True)
class NarrationResult:
    output_dir: Path
    notes_markdown: Path
    manifest_json: Path
    audio_dir: Path | None
    narrated_pptx: Path | None
    slide_count: int


def run_narration(options: NarrationOptions) -> NarrationResult:
    input_pptx = options.input_pptx.expanduser().resolve()
    if not input_pptx.exists():
        raise FileNotFoundError(f"Input PPTX does not exist: {input_pptx}")
    if input_pptx.suffix.lower() != ".pptx":
        raise ValueError(f"Input must be a .pptx file: {input_pptx}")
    if options.chars_per_second <= 0:
        raise ValueError("--chars-per-second must be greater than 0")

    output_dir = (
        options.output_dir.expanduser().resolve()
        if options.output_dir
        else Path.cwd() / f"{input_pptx.stem}_ppt_narrator"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    slides = extract_slide_notes(input_pptx)
    if options.slide_limit is not None:
        if options.slide_limit <= 0:
            raise ValueError("--slide-limit must be greater than 0")
        slides = slides[: options.slide_limit]
    notes_markdown = output_dir / "notes.md"
    manifest_json = output_dir / "manifest.json"
    audio_dir = None
    if options.audio_enabled:
        audio_dir = options.audio_input_dir.expanduser().resolve() if options.audio_input_dir else output_dir / "audio"
    narrated_pptx = (
        options.pptx_output.expanduser().resolve()
        if options.pptx_output
        else output_dir / f"{input_pptx.stem}.auto-narrated.pptx"
    ) if options.write_pptx else None

    planned_outputs = [notes_markdown, manifest_json]
    if narrated_pptx:
        planned_outputs.append(narrated_pptx)
    if options.audio_enabled:
        assert audio_dir is not None
        if options.audio_input_dir is None:
            planned_outputs.extend(audio_dir / f"page-{slide.index:03d}.wav" for slide in slides)
    for output_path in planned_outputs:
        _ensure_writable(output_path, options.overwrite)

    audio_entries = []
    if options.audio_enabled:
        assert audio_dir is not None
        if options.audio_input_dir:
            audio_entries = _load_external_audio_entries(options.audio_input_dir, slides)
        else:
            provider = build_tts_provider(
                options.provider,
                chars_per_second=options.chars_per_second,
                voice=options.voice,
                config_path=options.tts_config,
                language=options.language,
                doubao_resource_id=options.doubao_resource_id,
                doubao_voice_mode=options.doubao_voice_mode,
            )
            audio_dir.mkdir(parents=True, exist_ok=True)
            for slide in slides:
                audio_path = audio_dir / f"page-{slide.index:03d}.wav"
                audio_entries.append(provider.synthesize(slide.text, audio_path, options.voice))

    if narrated_pptx:
        if not audio_entries:
            raise RuntimeError("--write-pptx requires audio generation")
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

    return NarrationResult(
        output_dir=output_dir,
        notes_markdown=notes_markdown,
        manifest_json=manifest_json,
        audio_dir=audio_dir,
        narrated_pptx=narrated_pptx,
        slide_count=len(slides),
    )


def _ensure_writable(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file without --overwrite: {path}")


def _load_external_audio_entries(audio_input_dir: Path, slides: list[SlideNotes]) -> list[dict]:
    source_dir = audio_input_dir.expanduser().resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Audio input directory does not exist: {source_dir}")
    entries = []
    for slide in slides:
        audio_path = _find_external_audio_file(source_dir, slide.index)
        if audio_path is None:
            raise FileNotFoundError(f"Missing external audio for slide {slide.index}: {source_dir}/page-{slide.index:03d}.*")
        duration = probe_audio_duration(audio_path)
        if duration is None:
            raise RuntimeError(f"Cannot determine duration for external audio: {audio_path}")
        entries.append(
            {
                "slide_index": slide.index,
                "provider": "external",
                "voice": "external",
                "path": str(audio_path),
                "duration_seconds": duration,
            }
        )
    return entries


def _find_external_audio_file(source_dir: Path, slide_index: int) -> Path | None:
    for suffix in (".wav", ".mp3", ".m4a"):
        candidate = source_dir / f"page-{slide_index:03d}{suffix}"
        if candidate.exists():
            return candidate
    return None


def render_notes_markdown(input_pptx: Path, slides: list[SlideNotes]) -> str:
    lines = [
        f"# Narration Notes: {input_pptx.name}",
        "",
        "| Slide | Title | Characters | Has notes |",
        "| --- | --- | ---: | --- |",
    ]
    for slide in slides:
        title = slide.title.replace("|", "\\|")
        lines.append(f"| {slide.index} | {title} | {slide.character_count} | {'yes' if slide.text else 'no'} |")

    lines.append("")
    for slide in slides:
        lines.extend(
            [
                f"## Slide {slide.index}: {slide.title}",
                "",
                slide.text or "_No speaker notes found._",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_manifest(
    input_pptx: Path,
    slides: list[SlideNotes],
    audio_entries: list[dict],
    narrated_pptx: Path | None = None,
) -> dict:
    audio_by_slide = {entry["slide_index"]: entry for entry in audio_entries}
    return {
        "input": str(input_pptx),
        "slide_count": len(slides),
        "narrated_pptx": str(narrated_pptx) if narrated_pptx else None,
        "slides": [
            {
                "index": slide.index,
                "title": slide.title,
                "notes_path": slide.notes_path,
                "character_count": slide.character_count,
                "has_notes": bool(slide.text),
                "audio": audio_by_slide.get(slide.index),
            }
            for slide in slides
        ],
    }
