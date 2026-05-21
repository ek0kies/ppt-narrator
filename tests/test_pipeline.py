from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from ppt_narrator.audio import write_silence_wav
from ppt_narrator.cli import main
from ppt_narrator.pipeline import NarrationOptions, run_narration
from ppt_narrator.pptx_notes import extract_slide_notes
from ppt_narrator.tts import DOUBAO_DEFAULT_SPEAKER, DoubaoTTSProvider, build_tts_provider


class PptNarratorTests(unittest.TestCase):
    def test_extracts_notes_from_pptx_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "sample.pptx"
            _write_sample_pptx(pptx)

            slides = extract_slide_notes(pptx)

            self.assertEqual(len(slides), 2)
            self.assertEqual(slides[0].title, "Opening")
            self.assertEqual(slides[0].text, "第一页讲稿。")
            self.assertEqual(slides[1].title, "Slide 2")
            self.assertEqual(slides[1].text, "")

    def test_pipeline_writes_notes_manifest_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pptx = tmp_path / "sample.pptx"
            output = tmp_path / "out"
            _write_sample_pptx(pptx)

            result = run_narration(
                NarrationOptions(
                    input_pptx=pptx,
                    output_dir=output,
                    chars_per_second=10,
                    overwrite=False,
                )
            )

            self.assertEqual(result.slide_count, 2)
            self.assertTrue((output / "notes.md").exists())
            self.assertTrue((output / "manifest.json").exists())
            self.assertTrue((output / "audio" / "page-001.wav").exists())
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["slide_count"], 2)
            self.assertEqual(manifest["slides"][0]["audio"]["provider"], "dry-run")

    def test_pipeline_writes_auto_advance_pptx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pptx = tmp_path / "sample.pptx"
            output = tmp_path / "out"
            _write_sample_pptx(pptx)

            result = run_narration(
                NarrationOptions(
                    input_pptx=pptx,
                    output_dir=output,
                    write_pptx=True,
                )
            )

            self.assertIsNotNone(result.narrated_pptx)
            assert result.narrated_pptx is not None
            self.assertTrue(result.narrated_pptx.exists())
            with zipfile.ZipFile(result.narrated_pptx) as package:
                self.assertIn("ppt/media/ppt-narrator-page-001.wav", package.namelist())
                slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
                self.assertIn("advClick=\"0\"", slide_xml)
                self.assertIn("advTm=", slide_xml)
                rels_xml = package.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8")
                self.assertIn("/relationships/audio", rels_xml)

    def test_pipeline_can_start_audio_timing_node_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pptx = tmp_path / "sample.pptx"
            output = tmp_path / "out"
            _write_sample_pptx(pptx)

            result = run_narration(
                NarrationOptions(
                    input_pptx=pptx,
                    output_dir=output,
                    write_pptx=True,
                    direct_audio_start=True,
                )
            )

            assert result.narrated_pptx is not None
            with zipfile.ZipFile(result.narrated_pptx) as package:
                slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
                self.assertIn("<p:audio>", slide_xml)
                self.assertIn('delay="0"', slide_xml)
                self.assertNotIn('delay="indefinite"', slide_xml)

    def test_pipeline_can_use_transition_sound_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pptx = tmp_path / "sample.pptx"
            output = tmp_path / "out"
            _write_sample_pptx(pptx)

            result = run_narration(
                NarrationOptions(
                    input_pptx=pptx,
                    output_dir=output,
                    write_pptx=True,
                    audio_trigger="transition-sound",
                )
            )

            assert result.narrated_pptx is not None
            with zipfile.ZipFile(result.narrated_pptx) as package:
                slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
                rels_xml = package.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8")
                self.assertIn("<p:sndAc>", slide_xml)
                self.assertIn("<p:stSnd>", slide_xml)
                self.assertIn("<p:snd", slide_xml)
                self.assertNotIn("<p:audio>", slide_xml)
                self.assertIn("/relationships/audio", rels_xml)
                self.assertNotIn("office/2007/relationships/media", rels_xml)

    def test_pipeline_can_use_external_audio_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pptx = tmp_path / "sample.pptx"
            output = tmp_path / "out"
            external_audio = tmp_path / "external-audio"
            _write_sample_pptx(pptx)
            write_silence_wav(external_audio / "page-001.wav", 2.0)
            write_silence_wav(external_audio / "page-002.wav", 3.0)

            result = run_narration(
                NarrationOptions(
                    input_pptx=pptx,
                    output_dir=output,
                    audio_input_dir=external_audio,
                    write_pptx=True,
                    audio_trigger="transition-sound",
                )
            )

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            assert result.narrated_pptx is not None
            self.assertEqual(manifest["slides"][0]["audio"]["provider"], "external")
            self.assertEqual(manifest["slides"][0]["audio"]["duration_seconds"], 2.0)
            self.assertFalse((output / "audio").exists())
            with zipfile.ZipFile(result.narrated_pptx) as package:
                slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
                self.assertIn("advTm=\"2500\"", slide_xml)

    def test_slide_limit_processes_prefix_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pptx = tmp_path / "sample.pptx"
            output = tmp_path / "out"
            _write_sample_pptx(pptx)

            result = run_narration(
                NarrationOptions(
                    input_pptx=pptx,
                    output_dir=output,
                    slide_limit=1,
                )
            )

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result.slide_count, 1)
            self.assertEqual(len(manifest["slides"]), 1)
            self.assertTrue((output / "audio" / "page-001.wav").exists())
            self.assertFalse((output / "audio" / "page-002.wav").exists())

    def test_doubao_provider_reads_aivideoclip_config_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.cloud.local.json"
            config.write_text(
                json.dumps(
                    {
                        "production": {
                            "tts": {
                                "endpoint": "https://example.test/tts",
                                "api_key": "test-key",
                                "resource_id": "seed-tts-2.0",
                                "speaker_id": "speaker-1",
                                "sample_rate": 24000,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            provider = build_tts_provider(
                "doubao",
                chars_per_second=10,
                config_path=config,
                doubao_voice_mode="config",
            )

            self.assertIsInstance(provider, DoubaoTTSProvider)
            self.assertEqual(provider.endpoint, "https://example.test/tts")
            self.assertEqual(provider.resource_id, "seed-tts-2.0")
            self.assertEqual(provider.speaker, "speaker-1")
            self.assertEqual(provider.sample_rate, 24000)

    def test_doubao_builtin_mode_ignores_clone_config_voice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.cloud.local.json"
            config.write_text(
                json.dumps(
                    {
                        "production": {
                            "tts": {
                                "endpoint": "https://example.test/tts",
                                "api_key": "test-key",
                                "resource_id": "seed-icl-2.0",
                                "speaker_id": "S_cloned",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            provider = build_tts_provider("doubao", chars_per_second=10, config_path=config)

            self.assertIsInstance(provider, DoubaoTTSProvider)
            self.assertEqual(provider.resource_id, "seed-tts-2.0")
            self.assertEqual(provider.speaker, DOUBAO_DEFAULT_SPEAKER)
            self.assertEqual(provider.voice_mode, "builtin")

    def test_doubao_clone_mode_uses_clone_resource_and_config_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.cloud.local.json"
            config.write_text(
                json.dumps(
                    {
                        "production": {
                            "tts": {
                                "api_key": "test-key",
                                "resource_id": "seed-tts-2.0",
                                "speaker_id": "S_cloned",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            provider = build_tts_provider(
                "doubao",
                chars_per_second=10,
                config_path=config,
                doubao_voice_mode="clone",
            )

            self.assertIsInstance(provider, DoubaoTTSProvider)
            self.assertEqual(provider.resource_id, "seed-icl-2.0")
            self.assertEqual(provider.speaker, "S_cloned")
            self.assertEqual(provider.voice_mode, "clone")

    def test_cli_returns_nonzero_for_provider_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "sample.pptx"
            output = Path(tmp) / "out"
            config = Path(tmp) / "tts.json"
            _write_sample_pptx(pptx)
            config.write_text(json.dumps({"tts": {"speaker_id": "speaker-1"}}), encoding="utf-8")

            with redirect_stderr(StringIO()):
                exit_code = main(
                    [str(pptx), "--provider", "doubao", "--tts-config", str(config), "--output", str(output)]
                )

            self.assertEqual(exit_code, 1)


def _write_sample_pptx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", _content_types_xml())
        package.writestr("ppt/slides/slide1.xml", _slide_xml("Opening"))
        package.writestr("ppt/slides/slide2.xml", _slide_xml(""))
        package.writestr("ppt/slides/_rels/slide1.xml.rels", _rels_xml("../notesSlides/notesSlide1.xml"))
        package.writestr("ppt/slides/_rels/slide2.xml.rels", _rels_xml(""))
        package.writestr("ppt/notesSlides/notesSlide1.xml", _notes_xml("第一页讲稿。"))


def _slide_xml(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>
"""


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
</Types>
"""


def _notes_xml(text: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
         xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:notes>
"""


def _rels_xml(notes_target: str) -> str:
    note_relationship = (
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="{notes_target}"/>'
        if notes_target
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {note_relationship}
</Relationships>
"""


if __name__ == "__main__":
    unittest.main()
