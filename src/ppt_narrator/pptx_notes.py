from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
NOTES_REL_SUFFIX = "/notesSlide"


@dataclass(frozen=True)
class SlideNotes:
    index: int
    slide_path: str
    notes_path: str | None
    title: str
    text: str

    @property
    def character_count(self) -> int:
        return len("".join(self.text.split()))


def extract_slide_notes(pptx_path: Path) -> list[SlideNotes]:
    """Extract speaker notes from a PPTX package without modifying it."""
    with zipfile.ZipFile(pptx_path) as package:
        slide_paths = sorted(
            (name for name in package.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=_slide_number,
        )
        slides: list[SlideNotes] = []
        for index, slide_path in enumerate(slide_paths, start=1):
            notes_path = _resolve_notes_path(package, slide_path)
            title = _extract_title(package.read(slide_path))
            text = _extract_notes_text(package.read(notes_path)) if notes_path else ""
            slides.append(
                SlideNotes(
                    index=index,
                    slide_path=slide_path,
                    notes_path=notes_path,
                    title=title or f"Slide {index}",
                    text=text,
                )
            )
        return slides


def _slide_number(path: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", path)
    return int(match.group(1)) if match else 0


def _resolve_notes_path(package: zipfile.ZipFile, slide_path: str) -> str | None:
    rels_path = _rels_path_for(slide_path)
    if rels_path not in package.namelist():
        return None

    rels_root = ElementTree.fromstring(package.read(rels_path))
    for relationship in rels_root.findall(f"{{{REL_NS}}}Relationship"):
        rel_type = relationship.attrib.get("Type", "")
        if not rel_type.endswith(NOTES_REL_SUFFIX):
            continue
        target = relationship.attrib.get("Target")
        if not target:
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(slide_path), target))
        return resolved if resolved in package.namelist() else None
    return None


def _rels_path_for(part_path: str) -> str:
    directory = posixpath.dirname(part_path)
    filename = posixpath.basename(part_path)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def _extract_title(slide_xml: bytes) -> str:
    paragraphs = _extract_paragraphs(slide_xml)
    return paragraphs[0] if paragraphs else ""


def _extract_notes_text(notes_xml: bytes) -> str:
    paragraphs = _extract_paragraphs(notes_xml)
    return "\n\n".join(paragraphs)


def _extract_paragraphs(xml_bytes: bytes) -> list[str]:
    root = ElementTree.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for paragraph in root.findall(f".//{{{DRAWING_NS}}}p"):
        runs = [node.text or "" for node in paragraph.findall(f".//{{{DRAWING_NS}}}t")]
        text = _normalize_text("".join(runs))
        if text:
            paragraphs.append(text)
    return paragraphs


def _normalize_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()

