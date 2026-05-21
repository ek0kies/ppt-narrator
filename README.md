# ppt-narrator

`ppt-narrator` is a local-first CLI for turning a PowerPoint deck with speaker
notes into structured narration assets.

Current MVP:

- Read `.pptx` speaker notes.
- Export `notes.md` and `manifest.json`.
- Generate per-slide `.wav` audio through dry-run placeholders or a TTS provider.
- Reuse externally generated per-slide audio files from any TTS tool.
- Write optional auto-advance PPTX copies with embedded per-slide audio.

## Usage

```bash
PYTHONPATH=src python3 -m ppt_narrator.cli path/to/slides.pptx --output output-dir
```

Useful options:

```bash
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx --no-audio
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx --chars-per-second 14
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx --overwrite
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx --write-pptx --overwrite
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx --write-pptx --pptx-audio-format mp3 --direct-audio-start --overwrite
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx --write-pptx --audio-trigger transition-sound --overwrite
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx --write-pptx --audio-input-dir path/to/audio --audio-trigger transition-sound --overwrite
```

The original PPTX is never modified.

## Agent-first Usage

This repository includes a repo-local Codex Skill at `skills/ppt-narrator/`.
The Skill is the preferred entrypoint for non-technical users: the user can ask
an agent to create a WPS-friendly narrated PPTX, while the agent calls the CLI
with stable defaults.

Agent default behavior:

- keep the source PPTX unchanged
- use speaker notes as narration text
- use Doubao built-in TTS when configured
- accept external per-slide audio from any TTS tool
- write an editable PPTX, not an MP4
- use `transition-sound` for WPS-friendly autoplay

Wrapper example:

```bash
python3 skills/ppt-narrator/scripts/run.py slides.pptx \
  --provider doubao \
  --tts-config volcengine.local.json \
  --output output-dir \
  --overwrite
```

For external audio:

```bash
python3 skills/ppt-narrator/scripts/run.py slides.pptx \
  --audio-input-dir path/to/audio \
  --output output-dir \
  --overwrite
```

## TTS Sources

Generated PPTX timing is based on per-slide audio files. Audio can come from:

- `--provider dry-run`: silent placeholder WAV files for local testing.
- `--provider doubao`: built-in Doubao TTS integration.
- `--audio-input-dir`: externally generated `page-001.wav`, `page-002.mp3`, or
  `page-003.m4a` files from any TTS tool.

TTS providers write audio files first. This is intentional: stable event
playback needs deterministic page durations and should not depend on live TTS
streaming while presenting.

## Doubao TTS

```bash
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx \
  --provider doubao \
  --tts-config volcengine.local.json \
  --slide-limit 1 \
  --write-pptx \
  --audio-trigger transition-sound \
  --output output-dir \
  --overwrite
```

Supported credential sources:

- `--tts-config path/to/volcengine.local.json`
- `PPT_NARRATOR_TTS_CONFIG`
- `DOUBAO_TTS_API_KEY`, `DOUBAO_TTS_SPEAKER_ID`, `DOUBAO_TTS_RESOURCE_ID`
- AiVideoClip Studio V2 local cloud config shape

Secrets are read at runtime and are not written into `manifest.json`.

Doubao voice modes:

- `--doubao-voice-mode builtin` is the default. It uses `seed-tts-2.0` with
  `zh_male_jieshuoxiaoming_uranus_bigtts`, ignores cloned `speaker_id`
  values from fallback configs, and can be overridden with `--voice`.
- `--doubao-voice-mode clone` uses `seed-icl-2.0` and requires a cloned
  `speaker_id` from `--voice`, config, or `DOUBAO_TTS_SPEAKER_ID`.
- `--doubao-voice-mode config` preserves the config/env `resource_id` and
  speaker behavior.
- `--doubao-resource-id` overrides `X-Api-Resource-Id` explicitly.

`--write-pptx` creates a copy with generated audio files embedded into
`ppt/media/` and slide transition times set from the audio duration. Add
`--advance-padding-ms` to leave extra time after each page narration.
For WPS playback tests, use `--pptx-audio-format mp3 --direct-audio-start` to
embed MP3 media and start the audio timing node when each slide loads.
If WPS still refuses media autoplay, use `--audio-trigger transition-sound` to
bind each narration file to the slide transition sound instead of a visible
audio object.

## External Audio

Use this mode when another TTS tool generates the narration:

```bash
PYTHONPATH=src python3 -m ppt_narrator.cli slides.pptx \
  --audio-input-dir path/to/audio \
  --write-pptx \
  --audio-trigger transition-sound \
  --output output-dir \
  --overwrite
```

The directory must contain one audio file per processed slide:

```text
page-001.wav
page-002.wav
page-003.mp3
```
