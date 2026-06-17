# ppt-narrator

`ppt-narrator` is an AI Agent Native Skill for turning a PowerPoint deck with
speaker notes into an editable auto-playing narrated PPTX. It is designed for agent-first
usage: humans give an Agent a PPTX, and the Agent installs/checks/uses the skill
instead of asking the human to copy commands or configure runtime details.

## Give This To An AI Agent

Human users should not run the setup manually. Give this to the Agent:

```text
Install and enable this AI Agent Native Skill from GitHub:
https://github.com/ek0kies/ppt-narrator/tree/main/skills/ppt-narrator

Treat skills/ppt-narrator as the skill root.
Use your native skill installation mechanism. If no native installer exists,
clone or download the repository, copy/use that skill root, then run:
- scripts/install.sh
- scripts/doctor.sh
- tests/smoke.sh

Then use it to create an editable auto-playing narrated PPTX from my source PPTX.
Do not generate MP4. Keep the source PPTX unchanged.
```

The Agent should use existing GitHub credentials if the repository is private.
The Agent should proceed only after install, doctor, and smoke checks pass.

## Skill Package

Install target for Agents:

```text
https://github.com/ek0kies/ppt-narrator/tree/main/skills/ppt-narrator
```

Generic installation contract:

```text
1. Fetch repository https://github.com/ek0kies/ppt-narrator.
2. Use skills/ppt-narrator as the skill root.
3. Read skill.json and SKILL.md.
4. Run scripts/install.sh.
5. Run scripts/doctor.sh.
6. Run tests/smoke.sh.
7. Use scripts/run.sh for new PPTX work.
8. Use scripts/update.sh for conversation-driven revisions of an existing result.
```

Optional Codex-compatible install example:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --url https://github.com/ek0kies/ppt-narrator/tree/main/skills/ppt-narrator
```

Equivalent repo/path form:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo ek0kies/ppt-narrator \
  --path skills/ppt-narrator
```

The installable skill directory is self-contained:

```text
skills/ppt-narrator/
├── SKILL.md
├── skill.json
├── requirements.txt
├── agents/openai.yaml
├── scripts/install.sh
├── scripts/doctor.sh
├── scripts/run.sh
├── scripts/run.py
├── scripts/update.sh
├── scripts/update.py
├── runtime/src/ppt_narrator/
└── tests/smoke.sh
```

After installation, the runtime can be called directly by the installing Agent
via `scripts/run.sh`. Platforms with a skill registry may require restart or
reload to pick up metadata.

The expected user experience is natural language first:

```text
Create an editable auto-playing narrated PPTX from this deck.
```

For an existing result, the expected update experience is also natural language:

```text
Make slide 2 shorter and change slides 3-4 to the female voice.
```

The agent should then choose the right audio source, output directory, and
verification steps. For updates, the Agent should convert the user's request
into `update_request.json` and run `scripts/update.sh` against the previous
`manifest.json`. Non-technical users should not need to know install internals,
runtime flags, or the JSON contract.

Agent default behavior:

- keep the source PPTX unchanged
- use speaker notes as narration text
- use Doubao built-in TTS when configured
- accept external per-slide audio from any TTS tool
- revise previous results through a structured update action
- write an editable PPTX, not an MP4
- use `transition-sound` for presentation-app-compatible autoplay

Installed skill wrapper example:

```bash
SKILL_DIR=/path/to/installed/ppt-narrator
python3 "$SKILL_DIR/scripts/run.sh" slides.pptx \
  --provider doubao \
  --tts-config volcengine.local.json \
  --output output-dir \
  --overwrite
```

Self-check:

```bash
SKILL_DIR=/path/to/installed/ppt-narrator
"$SKILL_DIR/scripts/install.sh"
"$SKILL_DIR/scripts/doctor.sh"
"$SKILL_DIR/tests/smoke.sh"
```

For external audio:

```bash
SKILL_DIR=/path/to/installed/ppt-narrator
python3 "$SKILL_DIR/scripts/run.sh" slides.pptx \
  --audio-input-dir path/to/audio \
  --output output-dir \
  --overwrite
```

The original PPTX is never modified.

## Conversation Updates

`ppt-narrator` has a built-in update action for revising an existing narrated
result. The Agent interprets the conversation, writes a structured JSON request,
and the runtime applies it deterministically. The runtime does not call an LLM
or modify the source PPTX in place.

Example request JSON:

```json
{
  "slides": [
    {
      "index": 2,
      "text": "Updated narration for slide 2."
    }
  ]
}
```

Example update command:

```bash
SKILL_DIR=/path/to/installed/ppt-narrator
"$SKILL_DIR/scripts/update.sh" \
  --manifest output-dir/manifest.json \
  --request update_request.json \
  --output updated-output-dir \
  --provider doubao \
  --tts-config volcengine.local.json \
  --overwrite
```

Supported request fields:

| Field | Meaning |
| --- | --- |
| `slide_indexes` | Optional target slides for top-level `voice` or `regenerate_audio`. |
| `voice` | Optional default voice for targeted regenerated slides. |
| `regenerate_audio` | Force regeneration for targeted slides. |
| `slides[].index` | Required one-based slide index. |
| `slides[].text` | Replacement narration text for one slide. |
| `slides[].voice` | Per-slide voice override. |
| `slides[].audio_path` | External replacement audio file for one slide. |

## CLI Runtime

The CLI is the implementation layer used by the Skill. It is still useful for
development, testing, and automation.

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
PYTHONPATH=src python3 -m ppt_narrator.update --manifest output-dir/manifest.json --request update_request.json --output updated-output-dir --provider dry-run --overwrite
```

Dry-run agent smoke test:

```bash
python3 skills/ppt-narrator/scripts/run.sh slides.pptx \
  --provider dry-run \
  --slide-limit 1 \
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
For presentation-app compatibility tests, use `--pptx-audio-format mp3 --direct-audio-start` to
embed MP3 media and start the audio timing node when each slide loads.
If a presentation app refuses media autoplay, use `--audio-trigger transition-sound` to
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
