"""Plain-text and Markdown formatting for EduPage menu lines (no HA imports)."""

from __future__ import annotations

import re

_WEEKDAY_OPTION_RE = re.compile(
    r"^(Pon|Wt|Śr|Czw|Pt|So|Ni), \d{2}\.\d{2}\.\d{4}$"
)


def _normalize_menu_line(line: str) -> str:
    return re.sub(r"[ \t]+", " ", line.strip())


def _split_menu_lines(raw: str) -> list[str]:
    """Split EduPage menu text into one line per dish."""
    text = raw.strip()
    if not text:
        return []

    if "\n" in text:
        lines = []
        for ln in text.splitlines():
            ln = _normalize_menu_line(ln)
            if not ln or _WEEKDAY_OPTION_RE.match(ln):
                continue
            lines.append(ln)
        return lines

    return [
        _normalize_menu_line(part)
        for part in re.split(r"(?<=\))\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])", text)
        if part.strip()
    ]


def _format_dish_line(line: str) -> str:
    """Plain-text layout for Home Assistant calendar (no Markdown)."""
    line = _normalize_menu_line(line.replace("**", ""))
    if not line:
        return ""
    if " (" in line:
        name, _, rest = line.partition(" (")
        return f"• {name.strip()}\n  ({rest}"
    return f"• {line}"


def format_menu_description(raw: str) -> str:
    """Format raw menu text for calendar description."""
    stripped = re.sub(r"\*\*", "", raw.strip())
    lines = _split_menu_lines(stripped)
    if not lines:
        return re.sub(r"\s+", " ", stripped).strip()
    return "\n\n".join(_format_dish_line(line) for line in lines)


def _format_dish_markdown(line: str) -> str:
    line = _normalize_menu_line(line.replace("**", ""))
    if not line:
        return ""
    if " (" in line:
        name, _, rest = line.partition(" (")
        return f"- **{name.strip()}**\n  ({rest}"
    return f"- **{line}**"


def format_menu_markdown(raw: str) -> str:
    """Markdown list for Lovelace markdown cards."""
    stripped = re.sub(r"\*\*", "", raw.strip())
    lines = _split_menu_lines(stripped)
    if not lines:
        return re.sub(r"\s+", " ", stripped).strip()
    return "\n\n".join(_format_dish_markdown(line) for line in lines)