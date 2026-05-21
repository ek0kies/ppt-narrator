---
name: ppt-narrator
description: Installable agent-first skill for creating WPS-friendly narrated PPTX decks from PowerPoint speaker notes or externally generated per-slide audio. Use when a user asks to add voice-over, narration, TTS, automatic slide audio, or auto page turning to a PPTX without producing MP4.
---

# ppt-narrator

This is an installable Skill. It includes its own bundled Python runtime under
`runtime/src`, so an agent can install it from GitHub and run it without asking
the user to copy prompts or remember CLI flags.

## User Experience

The user should only provide:

- a source `.pptx`
- optionally a TTS config or an external audio folder
- optionally an output directory

Choose the execution path and run `scripts/run.py`.

## Default Outcome

Create a new editable PPTX that:

- keeps the source PPTX unchanged
- reads speaker notes as narration text
- creates or reuses one audio file per slide
- binds each audio file to slide transition sound for WPS-friendly autoplay
- sets slide advance time from audio duration
- does not generate MP4

## Decision Flow

1. If the user provides an audio folder, use external-audio mode.
2. Else if the user provides a TTS config or Doubao env vars are present, use
   Doubao built-in TTS.
3. Else if the user explicitly asks for a structural test, use dry-run.
4. Else ask for either a TTS config/API key setup or an external audio folder.

## Run

Prefer the bundled wrapper:

```bash
python3 scripts/run.py path/to/slides.pptx --output output-dir
```

Doubao:

```bash
python3 scripts/run.py path/to/slides.pptx \
  --provider doubao \
  --tts-config path/to/volcengine.local.json \
  --output output-dir \
  --overwrite
```

External audio:

```bash
python3 scripts/run.py path/to/slides.pptx \
  --audio-input-dir path/to/audio \
  --output output-dir \
  --overwrite
```

Dry-run structural test:

```bash
python3 scripts/run.py path/to/slides.pptx \
  --provider dry-run \
  --slide-limit 1 \
  --output output-dir \
  --overwrite
```

## Defaults

- playback trigger: `transition-sound`
- Doubao voice mode: `builtin`
- Doubao resource: `seed-tts-2.0`
- Doubao voice: `zh_male_jieshuoxiaoming_uranus_bigtts`
- output: PPTX only

## External Audio Contract

The audio directory must contain one file per processed slide:

```text
page-001.wav
page-002.mp3
page-003.m4a
```

Missing files are errors. Duration must be readable through `ffprobe` or WAV
metadata.

## Verify

After running:

1. Confirm `manifest.json` exists.
2. Confirm the output `.auto-narrated.pptx` exists.
3. Run `unzip -t <output.pptx>` when `unzip` is available.
4. Report the final PPTX path and whether the source PPTX was left unchanged.

## Safety

- Never write API keys into the repo or generated manifests.
- Never modify the source PPTX in place.
- Do not suggest MP4 unless the user explicitly changes the boundary.
- For WPS playback, prefer transition sound over media-object autoplay.
