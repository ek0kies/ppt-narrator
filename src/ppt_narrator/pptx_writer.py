from __future__ import annotations

import posixpath
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"

AUDIO_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio"
MEDIA_REL_TYPE = "http://schemas.microsoft.com/office/2007/relationships/media"

ElementTree.register_namespace("p", P_NS)
ElementTree.register_namespace("a", A_NS)
ElementTree.register_namespace("r", R_NS)
ElementTree.register_namespace("p14", P14_NS)


@dataclass(frozen=True)
class SlideAudio:
    slide_index: int
    audio_path: Path
    duration_seconds: float


def write_auto_advance_pptx(
    input_pptx: Path,
    output_pptx: Path,
    slide_audio: list[SlideAudio],
    advance_padding_ms: int = 500,
    embed_audio_format: str = "source",
    visible_audio_icon: bool = False,
    direct_audio_start: bool = False,
    audio_trigger: str = "media",
) -> Path:
    """Create a PPTX copy with per-slide audio assets and auto-advance timings."""
    if audio_trigger not in {"media", "transition-sound"}:
        raise ValueError(f"unsupported PPTX audio trigger: {audio_trigger}")
    input_pptx = input_pptx.expanduser().resolve()
    output_pptx = output_pptx.expanduser().resolve()
    output_pptx.parent.mkdir(parents=True, exist_ok=True)
    audio_by_slide = {item.slide_index: item for item in slide_audio}

    modified_entries: dict[str, bytes] = {}
    audio_entries: dict[str, bytes] = {}

    with zipfile.ZipFile(input_pptx, "r") as source:
        names = source.namelist()
        prepared_audio = [
            _prepare_audio_for_embed(item, output_pptx.parent, embed_audio_format)
            for item in slide_audio
        ]
        audio_by_slide = {item.slide_index: item for item in prepared_audio}

        content_types = _update_content_types(
            source.read("[Content_Types].xml"),
            suffixes={item.audio_path.suffix.lower() for item in prepared_audio},
        )
        modified_entries["[Content_Types].xml"] = content_types

        for slide_index, audio in audio_by_slide.items():
            slide_path = f"ppt/slides/slide{slide_index}.xml"
            if slide_path not in names:
                continue
            media_name = f"ppt/media/ppt-narrator-page-{slide_index:03d}{audio.audio_path.suffix.lower() or '.wav'}"
            audio_entries[media_name] = audio.audio_path.read_bytes()
            rels_path = _rels_path_for(slide_path)
            rels_xml = source.read(rels_path) if rels_path in names else _empty_relationships_xml()
            audio_rel_id, media_rel_id, updated_rels = _add_audio_relationship(
                rels_xml,
                media_name,
                slide_path,
                include_media=audio_trigger == "media",
            )
            modified_entries[rels_path] = updated_rels
            modified_entries[slide_path] = _update_slide_xml(
                source.read(slide_path),
                audio_rel_id=audio_rel_id,
                media_rel_id=media_rel_id,
                slide_index=slide_index,
                advance_ms=max(1, int(audio.duration_seconds * 1000) + advance_padding_ms),
                media_duration_ms=max(1, int(audio.duration_seconds * 1000)),
                visible_audio_icon=visible_audio_icon,
                direct_audio_start=direct_audio_start,
                audio_trigger=audio_trigger,
                sound_name=Path(media_name).name,
            )

        with zipfile.ZipFile(output_pptx, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                if item.filename in modified_entries:
                    target.writestr(item, modified_entries[item.filename])
                    continue
                target.writestr(item, source.read(item.filename))
            for name, content in audio_entries.items():
                target.writestr(name, content)

    return output_pptx


def _prepare_audio_for_embed(audio: SlideAudio, output_dir: Path, embed_audio_format: str) -> SlideAudio:
    requested = embed_audio_format.strip().lower()
    if requested in {"", "source"}:
        return audio
    if requested != "mp3":
        raise ValueError(f"unsupported PPTX audio embed format: {embed_audio_format}")
    target_dir = output_dir / "pptx-media"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"page-{audio.slide_index:03d}.mp3"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to create WPS-compatible MP3 PPTX audio")
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(audio.audio_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "ffmpeg failed"
        raise RuntimeError(f"failed to convert audio to mp3: {detail}")
    return SlideAudio(slide_index=audio.slide_index, audio_path=target, duration_seconds=audio.duration_seconds)


def _update_content_types(xml_bytes: bytes, suffixes: set[str]) -> bytes:
    root = ElementTree.fromstring(xml_bytes)
    for suffix in suffixes:
        extension = suffix.lstrip(".")
        if not extension:
            continue
        content_type = _audio_content_type(extension)
        if not content_type:
            continue
        has_default = any(
            child.tag == f"{{{CONTENT_TYPES_NS}}}Default" and child.attrib.get("Extension") == extension
            for child in root
        )
        if not has_default:
            ElementTree.SubElement(
                root,
                f"{{{CONTENT_TYPES_NS}}}Default",
                {"Extension": extension, "ContentType": content_type},
            )
    return _to_xml(root)


def _audio_content_type(extension: str) -> str:
    if extension == "wav":
        return "audio/wav"
    if extension == "mp3":
        return "audio/mpeg"
    if extension == "m4a":
        return "audio/mp4"
    return ""


def _add_audio_relationship(
    rels_xml: bytes,
    media_name: str,
    slide_path: str,
    include_media: bool = True,
) -> tuple[str, str, bytes]:
    root = ElementTree.fromstring(rels_xml)
    audio_rel_id = _next_relationship_id(root)
    media_rel_id = _next_relationship_id(root, reserved={audio_rel_id}) if include_media else ""
    target = posixpath.relpath(media_name, start=posixpath.dirname(slide_path))
    ElementTree.SubElement(
        root,
        f"{{{REL_NS}}}Relationship",
        {
            "Id": audio_rel_id,
            "Type": AUDIO_REL_TYPE,
            "Target": target,
        },
    )
    if include_media:
        ElementTree.SubElement(
            root,
            f"{{{REL_NS}}}Relationship",
            {
                "Id": media_rel_id,
                "Type": MEDIA_REL_TYPE,
                "Target": target,
            },
        )
    return audio_rel_id, media_rel_id, _to_xml(root)


def _update_slide_xml(
    xml_bytes: bytes,
    audio_rel_id: str,
    media_rel_id: str,
    slide_index: int,
    advance_ms: int,
    media_duration_ms: int,
    visible_audio_icon: bool,
    direct_audio_start: bool,
    audio_trigger: str,
    sound_name: str,
) -> bytes:
    root = ElementTree.fromstring(xml_bytes)
    _set_transition(
        root,
        advance_ms,
        sound_rel_id=audio_rel_id if audio_trigger == "transition-sound" else None,
        sound_name=sound_name,
    )
    if audio_trigger == "transition-sound":
        return _to_xml(root)
    shape_id = _append_audio_shape(root, audio_rel_id, media_rel_id, slide_index, visible_audio_icon)
    _set_audio_timing(root, shape_id, media_duration_ms, direct_audio_start)
    return _to_xml(root)


def _set_transition(
    root: ElementTree.Element,
    advance_ms: int,
    sound_rel_id: str | None = None,
    sound_name: str = "",
) -> None:
    transition = root.find(f"{{{P_NS}}}transition")
    if transition is None:
        transition = ElementTree.Element(f"{{{P_NS}}}transition", {"spd": "med"})
        root.append(transition)
    transition.attrib["advClick"] = "0"
    transition.attrib["advTm"] = str(advance_ms)
    for child in list(transition):
        if child.tag == f"{{{P_NS}}}sndAc":
            transition.remove(child)
    if sound_rel_id:
        snd_ac = ElementTree.SubElement(transition, f"{{{P_NS}}}sndAc")
        st_snd = ElementTree.SubElement(snd_ac, f"{{{P_NS}}}stSnd")
        ElementTree.SubElement(st_snd, f"{{{P_NS}}}snd", {f"{{{R_NS}}}embed": sound_rel_id, "name": sound_name})


def _append_audio_shape(
    root: ElementTree.Element,
    audio_rel_id: str,
    media_rel_id: str,
    slide_index: int,
    visible_audio_icon: bool,
) -> int:
    sp_tree = root.find(f".//{{{P_NS}}}spTree")
    if sp_tree is None:
        return 0
    shape_id = _next_shape_id(root)
    pic = ElementTree.Element(f"{{{P_NS}}}pic")
    nv_pic_pr = ElementTree.SubElement(pic, f"{{{P_NS}}}nvPicPr")
    c_nv_pr = ElementTree.SubElement(
        nv_pic_pr,
        f"{{{P_NS}}}cNvPr",
        {"id": str(shape_id), "name": f"ppt-narrator-audio-{slide_index:03d}"},
    )
    ElementTree.SubElement(c_nv_pr, f"{{{A_NS}}}hlinkClick", {f"{{{R_NS}}}id": "", "action": "ppaction://media"})
    c_nv_pic_pr = ElementTree.SubElement(nv_pic_pr, f"{{{P_NS}}}cNvPicPr")
    ElementTree.SubElement(c_nv_pic_pr, f"{{{A_NS}}}picLocks", {"noChangeAspect": "1"})
    nv_pr = ElementTree.SubElement(nv_pic_pr, f"{{{P_NS}}}nvPr")
    ElementTree.SubElement(nv_pr, f"{{{A_NS}}}audioFile", {f"{{{R_NS}}}link": audio_rel_id})
    ext_lst = ElementTree.SubElement(nv_pr, f"{{{P_NS}}}extLst")
    ext = ElementTree.SubElement(ext_lst, f"{{{P_NS}}}ext", {"uri": "{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}"})
    ElementTree.SubElement(ext, f"{{{P14_NS}}}media", {f"{{{R_NS}}}embed": media_rel_id})

    blip_fill = ElementTree.SubElement(pic, f"{{{P_NS}}}blipFill")
    ElementTree.SubElement(blip_fill, f"{{{A_NS}}}stretch")
    sp_pr = ElementTree.SubElement(pic, f"{{{P_NS}}}spPr")
    xfrm = ElementTree.SubElement(sp_pr, f"{{{A_NS}}}xfrm")
    if visible_audio_icon:
        ElementTree.SubElement(xfrm, f"{{{A_NS}}}off", {"x": "114300", "y": "114300"})
        ElementTree.SubElement(xfrm, f"{{{A_NS}}}ext", {"cx": "457200", "cy": "457200"})
    else:
        ElementTree.SubElement(xfrm, f"{{{A_NS}}}off", {"x": "0", "y": "0"})
        ElementTree.SubElement(xfrm, f"{{{A_NS}}}ext", {"cx": "1", "cy": "1"})
    geom = ElementTree.SubElement(sp_pr, f"{{{A_NS}}}prstGeom", {"prst": "rect"})
    ElementTree.SubElement(geom, f"{{{A_NS}}}avLst")

    sp_tree.append(pic)
    return shape_id


def _set_audio_timing(root: ElementTree.Element, shape_id: int, media_duration_ms: int, direct_audio_start: bool) -> None:
    if not shape_id:
        return
    child_tn_lst = _ensure_timing_child_list(root)
    next_id = _next_timing_id(root)
    seq = ElementTree.SubElement(child_tn_lst, f"{{{P_NS}}}seq", {"concurrent": "1", "nextAc": "seek"})
    seq_tn = ElementTree.SubElement(seq, f"{{{P_NS}}}cTn", {"id": str(next_id), "dur": "indefinite", "nodeType": "mainSeq"})
    next_id += 1
    seq_children = ElementTree.SubElement(seq_tn, f"{{{P_NS}}}childTnLst")
    par = ElementTree.SubElement(seq_children, f"{{{P_NS}}}par")
    par_tn = ElementTree.SubElement(par, f"{{{P_NS}}}cTn", {"id": str(next_id), "fill": "hold"})
    next_id += 1
    st_cond_lst = ElementTree.SubElement(par_tn, f"{{{P_NS}}}stCondLst")
    ElementTree.SubElement(st_cond_lst, f"{{{P_NS}}}cond", {"delay": "0"})
    par_children = ElementTree.SubElement(par_tn, f"{{{P_NS}}}childTnLst")
    media_call_par = ElementTree.SubElement(par_children, f"{{{P_NS}}}par")
    media_call_tn = ElementTree.SubElement(
        media_call_par,
        f"{{{P_NS}}}cTn",
        {
            "id": str(next_id),
            "presetID": "1",
            "presetClass": "mediacall",
            "presetSubtype": "0",
            "fill": "hold",
            "nodeType": "clickEffect",
        },
    )
    next_id += 1
    media_call_cond = ElementTree.SubElement(media_call_tn, f"{{{P_NS}}}stCondLst")
    ElementTree.SubElement(media_call_cond, f"{{{P_NS}}}cond", {"delay": "0"})
    media_call_children = ElementTree.SubElement(media_call_tn, f"{{{P_NS}}}childTnLst")
    cmd = ElementTree.SubElement(media_call_children, f"{{{P_NS}}}cmd", {"type": "call", "cmd": "playFrom(0.0)"})
    behavior = ElementTree.SubElement(cmd, f"{{{P_NS}}}cBhvr")
    ElementTree.SubElement(behavior, f"{{{P_NS}}}cTn", {"id": str(next_id), "dur": str(media_duration_ms), "fill": "hold"})
    next_id += 1
    tgt_el = ElementTree.SubElement(behavior, f"{{{P_NS}}}tgtEl")
    ElementTree.SubElement(tgt_el, f"{{{P_NS}}}spTgt", {"spid": str(shape_id)})

    audio = ElementTree.SubElement(child_tn_lst, f"{{{P_NS}}}audio")
    media_node = ElementTree.SubElement(audio, f"{{{P_NS}}}cMediaNode", {"vol": "80000"})
    ctn = ElementTree.SubElement(media_node, f"{{{P_NS}}}cTn", {"id": str(next_id), "fill": "hold", "display": "0"})
    st_cond_lst = ElementTree.SubElement(ctn, f"{{{P_NS}}}stCondLst")
    ElementTree.SubElement(st_cond_lst, f"{{{P_NS}}}cond", {"delay": "0" if direct_audio_start else "indefinite"})
    tgt_el = ElementTree.SubElement(media_node, f"{{{P_NS}}}tgtEl")
    ElementTree.SubElement(tgt_el, f"{{{P_NS}}}spTgt", {"spid": str(shape_id)})


def _ensure_timing_child_list(root: ElementTree.Element) -> ElementTree.Element:
    timing = root.find(f"{{{P_NS}}}timing")
    if timing is None:
        timing = ElementTree.SubElement(root, f"{{{P_NS}}}timing")
    tn_lst = timing.find(f"{{{P_NS}}}tnLst")
    if tn_lst is None:
        tn_lst = ElementTree.SubElement(timing, f"{{{P_NS}}}tnLst")
    par = tn_lst.find(f"{{{P_NS}}}par")
    if par is None:
        par = ElementTree.SubElement(tn_lst, f"{{{P_NS}}}par")
    root_tn = par.find(f"{{{P_NS}}}cTn")
    if root_tn is None:
        root_tn = ElementTree.SubElement(
            par,
            f"{{{P_NS}}}cTn",
            {"id": "1", "dur": "indefinite", "restart": "never", "nodeType": "tmRoot"},
        )
    child_tn_lst = root_tn.find(f"{{{P_NS}}}childTnLst")
    if child_tn_lst is None:
        child_tn_lst = ElementTree.SubElement(root_tn, f"{{{P_NS}}}childTnLst")
    return child_tn_lst


def _next_shape_id(root: ElementTree.Element) -> int:
    ids = []
    for element in root.findall(f".//{{{P_NS}}}cNvPr"):
        value = element.attrib.get("id")
        if value and value.isdigit():
            ids.append(int(value))
    return (max(ids) if ids else 1) + 1


def _next_timing_id(root: ElementTree.Element) -> int:
    ids = []
    for element in root.findall(f".//{{{P_NS}}}cTn"):
        value = element.attrib.get("id")
        if value and value.isdigit():
            ids.append(int(value))
    return (max(ids) if ids else 1) + 1


def _next_relationship_id(root: ElementTree.Element, reserved: set[str] | None = None) -> str:
    reserved = reserved or set()
    ids = []
    for rel in root.findall(f"{{{REL_NS}}}Relationship"):
        value = rel.attrib.get("Id", "")
        if value.startswith("rId") and value[3:].isdigit():
            ids.append(int(value[3:]))
    index = (max(ids) if ids else 0) + 1
    while f"rId{index}" in reserved:
        index += 1
    return f"rId{index}"


def _rels_path_for(part_path: str) -> str:
    directory = posixpath.dirname(part_path)
    filename = posixpath.basename(part_path)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def _empty_relationships_xml() -> bytes:
    root = ElementTree.Element(f"{{{REL_NS}}}Relationships")
    return _to_xml(root)


def _to_xml(root: ElementTree.Element) -> bytes:
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
