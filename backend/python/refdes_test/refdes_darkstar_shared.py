"""Lightweight shared helpers for RefDes Dark Star UI and logic."""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import IEEE_315_PREFIXES
from common.partition_id import strip_mode_suffixes, strip_status_suffixes

_CUSTOM_PREFIX_CONFIG = Path.home() / ".refdes_extractor_config.json"
POWER_SOURCE_RE = re.compile(r"\bP(?:\d+(?:\.\d+)?V|\dV\d)\b", re.I)


def _load_ref_prefixes() -> tuple[str, ...]:
    prefixes = [str(prefix).upper() for prefix in IEEE_315_PREFIXES]
    if _CUSTOM_PREFIX_CONFIG.exists():
        try:
            custom = json.loads(_CUSTOM_PREFIX_CONFIG.read_text(encoding="utf-8"))
            for prefix in custom.get("ref_prefixes", []):
                upper = str(prefix).strip().upper()
                if upper and upper not in prefixes:
                    prefixes.append(upper)
        except Exception:
            pass
    return tuple(prefixes)


REF_PREFIXES = _load_ref_prefixes()
REFDES_RE = re.compile(
    rf"\b(?:{'|'.join(sorted(REF_PREFIXES, key=len, reverse=True))})\d+[A-Z]?\b",
    re.I,
)

REFDES_BLACKLIST = {
    "uF",
    "mW",
    "1V",
    "3V",
    "5V",
    "12V",
    "15V",
    "16V",
    "28V",
    "GND",
    "AGND",
    "CGND",
    "SGND",
    "DGND",
    "VCC",
    "VIN",
    "VOUT",
    "OUT",
    "LDO",
    "Place",
    "Route",
    "Short",
    "PROV",
    "NC",
    "caps",
    "sensor",
    "temp",
    "MOSFET",
    "Func",
    "COMP1",
    "PGOOD1",
    "PGOOD2",
}

_BLACKLIST_UPPER = frozenset(item.upper() for item in REFDES_BLACKLIST)


def strip_mode_suffix(group_name: str) -> str:
    """Strip Dark Star mode/status suffixes while preserving the base label."""
    result, _status_suffixes = strip_status_suffixes(group_name)
    result, _mode_suffixes = strip_mode_suffixes(result)
    return result if result else group_name.strip()


def strip_suffix(refdes: str) -> str:
    """Strip a trailing section letter from a base RefDes using configured prefixes."""
    upper = str(refdes or "").strip().upper()
    if not upper or re.fullmatch(r"[A-Z]+", upper):
        return upper
    match = re.match(
        rf"^({'|'.join(REF_PREFIXES)})(\d+)([A-Z])?$",
        upper,
        re.I,
    )
    if match:
        return f"{match.group(1)}{match.group(2)}".upper()
    return upper


__all__ = [
    "REFDES_BLACKLIST",
    "_BLACKLIST_UPPER",
    "POWER_SOURCE_RE",
    "REFDES_RE",
    "REF_PREFIXES",
    "strip_mode_suffix",
    "strip_suffix",
]
