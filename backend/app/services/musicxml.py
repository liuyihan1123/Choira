"""MusicXML 读取、声部（part）识别与"裁剪式"拆分。

设计要点：
1. 拆分采用 **XML 级裁剪**：只保留目标 <part> 与对应 <score-part>，其余节点原样深拷贝。
   这样能保留原谱的歌词对齐、连音线、力度记号、移调等排版信息（music21 重新写出会丢）。
2. 顺手清理总谱里的分页/换行提示（<print new-page/new-system>），让单声部重新自动排版，
   避免出现"总谱宽度的系统被硬塞进单声部页面"的难看病。
3. 对"一个 part 内部叠了多个声部（SATB 写在两行钢琴谱表上）"的情况**明确标记为不可按 part 拆分**，
   交给人工映射，而不是偷偷做启发式切割。
"""

from __future__ import annotations

import copy
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

from lxml import etree

from .role_detect import suggest_role

SOFTWARE = "ChoirParts 0.1"


class MusicXmlError(ValueError):
    """无法解析或处理的 MusicXML 文件。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _ln(tag) -> str:
    """取本地标签名（忽略命名空间与注释/PI）。"""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def kids(el, name: str):
    return [c for c in el if _ln(c.tag) == name]


def kid(el, name: str):
    for c in el:
        if _ln(c.tag) == name:
            return c
    return None


def kid_text(el, *path: str) -> str:
    cur = el
    for name in path:
        if cur is None:
            return ""
        cur = kid(cur, name)
    if cur is None or cur.text is None:
        return ""
    return cur.text.strip()


def _strip_namespaces(root):
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = _ln(el.tag)
        for key in list(el.attrib):
            if key.startswith("{"):
                el.attrib[_ln(key)] = el.attrib.pop(key)
    return root


def _parse_root(xml_bytes: bytes):
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, recover=False, huge_tree=False
    )
    try:
        return etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as exc:  # pragma: no cover - 依赖坏输入
        raise MusicXmlError(f"XML 解析失败：{exc}") from exc


def extract_musicxml_bytes(raw: bytes, filename: str = "") -> bytes:
    """从 .musicxml / .xml / .mxl(ZIP) 中取出 MusicXML 文本。"""
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                target = None
                if "META-INF/container.xml" in names:
                    container = etree.fromstring(zf.read("META-INF/container.xml"))
                    for node in container.iter():
                        if _ln(node.tag) == "rootfile" and node.get("full-path"):
                            target = node.get("full-path")
                            break
                if target is None or target not in names:
                    candidates = [
                        n for n in names
                        if n.lower().endswith((".xml", ".musicxml"))
                        and not n.startswith("META-INF")
                    ]
                    if not candidates:
                        raise MusicXmlError("压缩包里没有找到 MusicXML 文件")
                    target = candidates[0]
                return zf.read(target)
        except zipfile.BadZipFile as exc:
            raise MusicXmlError("不是有效的 .mxl 压缩包") from exc
    return raw


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class PartInfo:
    part_id: str
    index: int
    name: str
    abbreviation: str
    staves: int
    clefs: list[str]
    voices: list[str]
    note_count: int
    multi_voice: bool
    extractable: bool
    suggested_role: str | None
    confidence: float
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "part_id": self.part_id,
            "index": self.index,
            "name": self.name,
            "abbreviation": self.abbreviation,
            "staves": self.staves,
            "clefs": self.clefs,
            "voices": self.voices,
            "note_count": self.note_count,
            "multi_voice": self.multi_voice,
            "extractable": self.extractable,
            "suggested_role": self.suggested_role,
            "confidence": round(self.confidence, 2),
            "warnings": self.warnings,
        }


@dataclass
class ScoreDocument:
    root: etree._Element
    version: str
    title: str
    composer: str
    parts: list[PartInfo]
    content_hash: str

    def part(self, part_id: str) -> PartInfo | None:
        return next((p for p in self.parts if p.part_id == part_id), None)


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

_CLEF_NAMES = {"G": "高音谱号", "F": "低音谱号", "C": "中音谱号", "percussion": "打击乐谱号", "TAB": "TAB"}


def _detect_meta(root) -> tuple[str, str]:
    title = kid_text(root, "work", "work-title") or kid_text(root, "movement-title")
    composer = ""
    ident = kid(root, "identification")
    if ident is not None:
        for creator in kids(ident, "creator"):
            if (creator.get("type") or "").lower() == "composer":
                composer = (creator.text or "").strip()
                break
        if not composer:
            creators = kids(ident, "creator")
            if creators:
                composer = (creators[0].text or "").strip()
    if not composer:
        # 很多时候作者写在 credit 里（title page）
        for credit in kids(root, "credit"):
            for words in kids(credit, "credit-words"):
                text = (words.text or "").strip()
                if text and re.search(r"(?i)(composer|曲|词|arr)", text):
                    composer = text
                    break
            if composer:
                break
    return title.strip(), composer.strip()


def _part_staves(part) -> int:
    best = 1
    for attributes in part.iter():
        if _ln(attributes.tag) != "attributes":
            continue
        staves = kid_text(attributes, "staves")
        if staves.isdigit():
            best = max(best, int(staves))
    return best


def _part_clefs(part) -> list[str]:
    found: list[str] = []
    for clef in part.iter():
        if _ln(clef.tag) != "clef":
            continue
        sign = kid_text(clef, "sign") or "?"
        line = kid_text(clef, "line")
        label = _CLEF_NAMES.get(sign, sign)
        if line:
            label = f"{label}({line}线)"
        if label not in found:
            found.append(label)
    return found


def _part_voices(part, max_measures: int = 80) -> list[str]:
    voices: list[str] = []
    for idx, measure in enumerate(part.iter()):
        if _ln(measure.tag) != "measure":
            continue
        for note in measure.iter():
            if _ln(note.tag) not in ("note", "backup", "forward"):
                continue
            voice = kid_text(note, "voice")
            if voice and voice not in voices:
                voices.append(voice)
        if idx > max_measures * 40:
            break
    return sorted(voices, key=lambda v: (len(v), v))


def _part_note_count(part) -> int:
    return sum(1 for n in part.iter() if _ln(n.tag) == "note")


def parse_score(raw: bytes, filename: str = "") -> ScoreDocument:
    xml_bytes = extract_musicxml_bytes(raw, filename)
    root = _parse_root(xml_bytes)
    if root.tag.startswith("{"):
        root = _strip_namespaces(root)
    tag = _ln(root.tag)
    if tag != "score-partwise":
        if tag == "score-timewise":
            raise MusicXmlError(
                "检测到 score-timewise 格式（按小节组织）。请先用 MuseScore 另存为 "
                "score-partwise 的 MusicXML 再上传。"
            )
        raise MusicXmlError(f"不是 MusicXML 总谱文件（根节点为 <{tag}>）")

    title, composer = _detect_meta(root)
    part_list = kid(root, "part-list")
    if part_list is None:
        raise MusicXmlError("缺少 <part-list>，文件可能不完整")

    scores: dict[str, etree._Element] = {}
    for sp in kids(part_list, "score-part"):
        pid = sp.get("id") or ""
        if pid:
            scores[pid] = sp

    content_parts = [p for p in kids(root, "part")]
    if not content_parts:
        raise MusicXmlError("总谱里没有任何 <part> 内容")

    infos: list[PartInfo] = []
    for index, part in enumerate(content_parts):
        pid = part.get("id") or f"P{index + 1}"
        sp = scores.get(pid)
        name = kid_text(sp, "part-name") if sp is not None else ""
        abbrev = kid_text(sp, "part-abbreviation") if sp is not None else ""
        name = name or f"Part {index + 1}"
        staves = _part_staves(part)
        voices = _part_voices(part)
        note_count = _part_note_count(part)
        warnings: list[str] = []

        multi_voice = len(voices) >= 3 or (staves >= 2 and len(voices) >= 3)
        if staves >= 2 and len(voices) >= 3:
            warnings.append(
                f"该 part 有 {staves} 行谱表 / {len(voices)} 个声部，很可能把合唱声部叠在钢琴缩编谱上；"
                "按 part 拆分无法分开，需要先在 MuseScore 里拆成独立 part"
            )
        elif len(voices) >= 2 and staves == 1:
            warnings.append(f"该 part 单谱表内有 {len(voices)} 个声部（divisi？），拆分后会合并为一行谱")

        role, confidence = suggest_role(name, abbrev, index)
        infos.append(
            PartInfo(
                part_id=pid,
                index=index,
                name=name,
                abbreviation=abbrev,
                staves=staves,
                clefs=_part_clefs(part),
                voices=voices,
                note_count=note_count,
                multi_voice=multi_voice,
                extractable=not multi_voice,
                suggested_role=role,
                confidence=confidence,
                warnings=warnings,
            )
        )

    return ScoreDocument(
        root=root,
        version=root.get("version") or "3.1",
        title=title,
        composer=composer,
        parts=infos,
        content_hash=hashlib.sha256(xml_bytes).hexdigest(),
    )


# ---------------------------------------------------------------------------
# 拆分导出
# ---------------------------------------------------------------------------

_DOCTYPE = {
    "4.0": '"-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd"',
    "3.1": '"-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd"',
    "3.0": '"-//Recordare//DTD MusicXML 3.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd"',
}


def _strip_layout(part) -> None:
    """清掉总谱的分页/换行提示，让单声部重新自动排版。"""
    for node in list(part.iter()):
        if not isinstance(node.tag, str) or _ln(node.tag) != "print":
            continue
        for attr in ("new-system", "new-page", "blank-page"):
            node.attrib.pop(attr, None)
        for child in list(node):
            if _ln(child.tag) in ("system-layout", "page-layout", "staff-layout"):
                node.remove(child)
        if len(node) == 0 and not node.attrib:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)


def _set_identification(root, watermark: str, source_title: str, part_name: str) -> None:
    ident = kid(root, "identification")
    if ident is None:
        ident = etree.Element("identification")
        part_list = kid(root, "part-list")
        if part_list is not None:
            part_list.addprevious(ident)
        else:
            root.insert(0, ident)

    encoding = kid(ident, "encoding")
    if encoding is None:
        encoding = etree.SubElement(ident, "encoding")
    for sw in kids(encoding, "software"):
        encoding.remove(sw)
    etree.SubElement(encoding, "software").text = SOFTWARE
    etree.SubElement(encoding, "encoding-date").text = date.today().isoformat()

    misc = kid(ident, "miscellaneous")
    if misc is None:
        misc = etree.SubElement(ident, "miscellaneous")
    fields = {
        "watermark": watermark,
        "source-score": source_title,
        "extracted-part": part_name,
        "note": "本文件由 ChoirParts 从总谱自动拆分，仅授权给对应声部成员使用",
    }
    for name, value in fields.items():
        f = etree.SubElement(misc, "miscellaneous-field")
        f.set("name", name)
        f.text = value


def _retitle(root, title: str, composer: str) -> None:
    """把分谱上的标题/作曲替换成曲目库里的值（也同步 credit-words）。"""
    if title:
        work = kid(root, "work")
        if work is None:
            work = etree.Element("work")
            root.insert(0, work)
        work_title = kid(work, "work-title")
        if work_title is None:
            work_title = etree.SubElement(work, "work-title")
        work_title.text = title
        movement = kid(root, "movement-title")
        if movement is not None:
            movement.text = title

    ident = kid(root, "identification")
    if ident is not None and composer:
        done = False
        for creator in kids(ident, "creator"):
            if (creator.get("type") or "").lower() == "composer":
                creator.text = composer
                done = True
                break
        if not done:
            creator = etree.Element("creator", type="composer")
            creator.text = composer
            ident.insert(0, creator)

    for credit in kids(root, "credit"):
        ctype = kid_text(credit, "credit-type")
        if ctype not in ("title", "subtitle", "composer"):
            continue
        words = kids(credit, "credit-words")
        if not words:
            continue
        if ctype == "title" and title:
            words[0].text = title
        elif ctype == "composer" and composer:
            words[0].text = composer


def _measure_tempo(measure) -> float | None:
    """取一小节里的速度标记（BPM），优先 <sound tempo>，退回 <per-minute>。"""
    for node in measure.iter():
        if _ln(node.tag) == "sound":
            raw = node.get("tempo")
            if raw:
                try:
                    return float(raw)
                except ValueError:
                    pass
    for node in measure.iter():
        if _ln(node.tag) == "per-minute":
            try:
                return float((node.text or "").strip())
            except ValueError:
                pass
    return None


def collect_tempos(doc: ScoreDocument) -> dict[int, float]:
    """按小节序号收集整份总谱的速度标记。

    分谱拆开之后，速度标记通常只留在其中一个声部（一般是最上面那个）的 XML 里。
    如果直接逐声部渲染，那个声部按 76 BPM 走、其余声部回落到 Verovio 默认的
    120 BPM，同一首曲子的各声部音频就会彻底错位。所以先把总谱的速度按小节抽出，
    生成音频时再统一写回每份分谱。
    """
    tempos: dict[int, float] = {}
    for part in kids(doc.root, "part"):
        for index, measure in enumerate(kids(part, "measure")):
            if index in tempos:
                continue
            bpm = _measure_tempo(measure)
            if bpm:
                tempos[index] = bpm
    return tempos


def _align_tempos(root, tempos: dict[int, float]) -> None:
    """把统一的速度标记写进每份分谱（先清掉只属于某个声部的旧标记）。"""
    for part in kids(root, "part"):
        for index, measure in enumerate(kids(part, "measure")):
            for node in list(measure.iter()):
                if isinstance(node.tag, str) and _ln(node.tag) == "sound" and node.get("tempo") is not None:
                    parent = node.getparent()
                    if parent is not None:
                        parent.remove(node)
            bpm = tempos.get(index)
            if bpm:
                sound = etree.Element("sound")
                sound.set("tempo", f"{bpm:g}")
                measure.insert(0, sound)


def extract_parts(
    doc: ScoreDocument,
    part_ids: Sequence[str],
    *,
    watermark: str = "",
    strip_layout: bool = True,
    title: str = "",
    composer: str = "",
    tempos: dict[int, float] | None = None,
) -> bytes:
    """把 doc 中指定的 part 另存为一份独立 MusicXML。"""
    keep = [pid for pid in part_ids if doc.part(pid) is not None]
    if not keep:
        raise MusicXmlError("没有选中任何可导出的声部")

    root = copy.deepcopy(doc.root)

    # 1) 重建 part-list：只留目标 <score-part>；丢弃 part-group（避免出现不配对的 start/stop）
    part_list = kid(root, "part-list")
    if part_list is not None:
        new_list = etree.Element("part-list")
        for sp in kids(part_list, "score-part"):
            if sp.get("id") in keep:
                new_list.append(copy.deepcopy(sp))
        part_list.getparent().replace(part_list, new_list)

    # 2) 删除未选中的 <part>
    for part in list(kids(root, "part")):
        if part.get("id") not in keep:
            root.remove(part)

    # 3) 保留 part 的排版清理
    kept_parts = kids(root, "part")
    for part in kept_parts:
        if strip_layout:
            _strip_layout(part)

    # 4) 速度对齐：分谱共用总谱的同一份速度表，音频才不会错位
    if tempos:
        _align_tempos(root, tempos)

    names = " / ".join(doc.part(pid).name for pid in keep if doc.part(pid))
    display_title = title or doc.title or "未命名总谱"
    _retitle(root, title, composer)
    _set_identification(
        root,
        watermark=watermark or f"{display_title} · {names}",
        source_title=display_title,
        part_name=names,
    )

    body = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    doctype = _DOCTYPE.get(doc.version)
    if doctype:
        decl_end = body.find(b"?>") + 2
        body = body[:decl_end] + b"\n<!DOCTYPE score-partwise PUBLIC " + doctype.encode() + b">" + body[decl_end:]
    return body


def summarize_for_ui(doc: ScoreDocument) -> dict:
    return {
        "title": doc.title,
        "composer": doc.composer,
        "musicxml_version": doc.version,
        "content_hash": doc.content_hash,
        "part_count": len(doc.parts),
        "parts": [p.as_dict() for p in doc.parts],
        "splittable": any(p.extractable for p in doc.parts),
    }
