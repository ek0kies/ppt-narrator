---
name: ppt-narrator
description: Agent-first workflow for turning PPTX speaker notes into a WPS-friendly auto-playing narrated PPTX. Use when the user asks to add narration, voice-over, TTS, auto page turning, WPS playback, or per-slide audio to a PowerPoint deck. Supports Doubao as the default built-in provider and external per-slide audio from any TTS tool.
---

# ppt-narrator

Use this skill to produce an editable `.pptx` that plays narration automatically
in WPS/PowerPoint-style presentation flows. The user should not need to know the
CLI flags.

## Default Outcome

Generate a new PPTX copy that:

- keeps the source PPTX unchanged
- reads speaker notes as narration text
- creates or reuses one audio file per slide
- binds each audio file to slide transition sound
- sets slide advance time from audio duration
- does not generate MP4

## Agent Workflow

1. Identify the source `.pptx`.
2. Decide the audio source:
   - If the user provides an audio folder, use external audio mode.
   - If the user asks for Doubao or gives a Doubao config/env, use Doubao.
   - If no TTS credentials or audio folder are available, ask for a TTS config,
     API key setup, or an external audio folder before creating a final deck.
   - Use dry-run only for structural tests or when explicitly requested.
3. Choose an output directory. Prefer a task-specific directory, not the source
   deck folder.
4. Run the wrapper script in `scripts/run.py` when available. It applies the
   WPS-safe defaults.
5. Verify:
   - command exits successfully
   - `manifest.json` exists
   - output PPTX exists
   - `unzip -t <output.pptx>` succeeds when `unzip` is available
6. Return the output PPTX path and any warnings.

## Standard Commands

From the repository root:

```bash
python3 skills/ppt-narrator/scripts/run.py path/to/slides.pptx \
  --provider doubao \
  --tts-config path/to/volcengine.local.json \
  --output output-dir
```

External audio mode:

```bash
python3 skills/ppt-narrator/scripts/run.py path/to/slides.pptx \
  --audio-input-dir path/to/audio \
  --output output-dir
```

Dry-run structural test:

```bash
python3 skills/ppt-narrator/scripts/run.py path/to/slides.pptx \
  --provider dry-run \
  --output output-dir
```

## Defaults

- `--write-pptx`
- `--audio-trigger transition-sound`
- Doubao voice mode: `builtin`
- Doubao voice: `zh_male_jieshuoxiaoming_uranus_bigtts`
- No MP4 output

## External Audio Contract

The audio directory must contain one file per processed slide:

```text
page-001.wav
page-002.mp3
page-003.m4a
```

Missing files are errors. Duration must be readable through `ffprobe` or WAV
metadata.

## Safety

- Do not write API keys into the repo or generated manifests.
- Do not modify the source PPTX.
- Do not suggest MP4 unless the user explicitly changes the project boundary.
- For WPS playback, prefer `transition-sound` over media-object autoplay.
