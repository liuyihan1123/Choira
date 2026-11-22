"""声部名 → 角色 的归一化映射。

真实总谱的 <part-name> 五花八门：Soprano / SOPRANO I / S. / 女高音 / Voice 1 / Choir ...
这里给出可解释的关键词规则，返回 (role, confidence)；置信度低的交给管理员在界面上确认。
"""

from __future__ import annotations

import re
import unicodedata

ROLES: dict[str, dict] = {
    "S": {"name": "女高音", "en": "Soprano", "short": "S", "color": "#e0534f"},
    "A": {"name": "女低音", "en": "Alto", "short": "A", "color": "#d97706"},
    "T": {"name": "男高音", "en": "Tenor", "short": "T", "color": "#0f766e"},
    "B": {"name": "男低音", "en": "Bass", "short": "B", "color": "#1d4ed8"},
    "ACCOMP": {"name": "伴奏", "en": "Accompaniment", "short": "Pno", "color": "#6b7280"},
    "CONDUCTOR": {"name": "指挥", "en": "Conductor", "short": "Cond", "color": "#7c3aed"},
}

ROLE_ORDER = ["S", "A", "T", "B", "ACCOMP", "CONDUCTOR"]

# 顺序有意义：先匹配更具体的（"Bassoon" 不该命中 bass）
_RULES: list[tuple[str, str]] = [
    ("CONDUCTOR", r"\bconductor\b|\bcond\.?|\bdirector\b|指挥"),
    ("ACCOMP", r"\bpiano\b|\bpianoforte\b|\bpf\b|\bpno\b|\baccomp\w*|\borgan\b|\bkeyboard\b|"
               r"\bharpsichord\b|钢琴|伴奏|键盘|管风琴|羽管键琴"),
    ("S", r"\bsopran\w*|\bsopr?\b|\bs\.?\s?[12]?\b|女高音|女高|高音部|高声部|高音"),
    ("A", r"\balto\w*|\bcontralto\w*|\balt\b|\ba\.?\s?[12]?\b|女低音|女低|中音部|中音"),
    ("T", r"\btenor\w*|\bten\.?\b|\bt\.?\s?[12]?\b|男高音|男高|男高声部"),
    ("B", r"\bbass(es)?\b|\bbass[12]\b|\bbassos?\b|\bbassus\b|\bbariton\w*|\bb\.?\s?[12]?\b|男低音|男低|低音部|低音"),
]

_COMPILED = [(role, re.compile(pat, re.IGNORECASE)) for role, pat in _RULES]

# 单 / 双字母缩写（part-abbreviation 常是 "S.", "S1", "A2", "Pno."）
_ABBREV = {
    "s": "S", "s1": "S", "s2": "S", "so": "S",
    "a": "A", "a1": "A", "a2": "A", "al": "A",
    "t": "T", "t1": "T", "t2": "T", "te": "T",
    "b": "B", "b1": "B", "b2": "B", "ba": "B",
    "pn": "ACCOMP", "pno": "ACCOMP", "pf": "ACCOMP", "piano": "ACCOMP", "org": "ACCOMP",
    "cond": "CONDUCTOR", "c": "CONDUCTOR",
}

_GENERIC = re.compile(r"^(voice|part|staff|track|choir|chorus|voice\s*\d+|part\s*\d+|声部|声部\s*\d+)$", re.IGNORECASE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip().lower()
    text = re.sub(r"[\(\)\[\]【】（）:：\-–—_/·,，.。'\"’]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def suggest_role(name: str, abbrev: str = "", index: int = 0) -> tuple[str | None, float]:
    """返回 (角色代码, 置信度 0~1)。无法判断时返回 (None, 0.0)。"""
    candidates = [normalize(name), normalize(abbrev)]
    for raw in candidates:
        if not raw:
            continue
        compact = raw.replace(" ", "")
        if compact in _ABBREV:
            return _ABBREV[compact], 0.9
        for role, pattern in _COMPILED:
            if pattern.search(raw):
                # 只命中一个词时略降置信度，避免 "choir alto" 之类混着写的名字被过度自信
                conf = 0.95 if re.fullmatch(r"[a-z\u4e00-\u9fff]+", compact) else 0.85
                return role, conf
    return None, 0.0


def is_generic_name(name: str) -> bool:
    return bool(_GENERIC.match(normalize(name)))
