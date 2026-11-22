from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.util import dt as dt_util

from .menu_format import format_menu_markdown

WEEKDAYS_PL = ("Pon", "Wt", "Śr", "Czw", "Pt", "So", "Ni")


def date_label(day: dt.date) -> str:
    """Human-friendly date label for select options."""
    return f"{WEEKDAYS_PL[day.weekday()]}, {day.strftime('%d.%m.%Y')}"


def label_to_date(label: str, items: list[dict[str, Any]]) -> dt.date | None:
    """Resolve select label back to a date."""
    for item in items:
        day = item.get("date")
        if isinstance(day, dt.date) and date_label(day) == label:
            return day
    return None


def items_by_date(items: list[dict[str, Any]]) -> dict[dt.date, dict[str, Any]]:
    return {
        item["date"]: item
        for item in items
        if isinstance(item.get("date"), dt.date)
    }


def next_school_menu_day(from_day: dt.date) -> dt.date:
    """Next school day after from_day (Fri/Sat/Sun → following Monday)."""
    weekday = from_day.weekday()
    if weekday == 4:
        return from_day + dt.timedelta(days=3)
    if weekday == 5:
        return from_day + dt.timedelta(days=2)
    if weekday == 6:
        return from_day + dt.timedelta(days=1)
    return from_day + dt.timedelta(days=1)


def next_menu_date(items: list[dict[str, Any]]) -> dt.date | None:
    """Menu for the next school day from today (skips weekends)."""
    by_date = items_by_date(items)
    if not by_date:
        return None

    target = next_school_menu_day(dt_util.now().date())
    for day in sorted(by_date):
        if day >= target:
            return day
    return None


def calendar_today_menu_date(items: list[dict[str, Any]]) -> dt.date | None:
    """Calendar today only when that day exists in the menu data."""
    today = dt_util.now().date()
    by_date = items_by_date(items)
    return today if today in by_date else None


def default_menu_date(items: list[dict[str, Any]]) -> dt.date | None:
    """Pick today when available, otherwise the nearest future day."""
    by_date = items_by_date(items)
    if not by_date:
        return None

    today = dt_util.now().date()
    if today in by_date:
        return today

    for day in sorted(by_date):
        if day >= today:
            return day

    return max(by_date)


def resolve_today_menu_date(
    items: list[dict[str, Any]], *, fallback_next: bool
) -> dt.date | None:
    """Menu — today: strict calendar day or optional fallback to next available."""
    if (today := calendar_today_menu_date(items)) is not None:
        return today
    if fallback_next:
        return default_menu_date(items)
    return None


def menu_title(day: dt.date, *, show_weekday: bool) -> str:
    if show_weekday:
        return f"Jadłospis ({WEEKDAYS_PL[day.weekday()]}, {day.strftime('%d.%m.%Y')})"
    return f"Jadłospis ({day.strftime('%d.%m.%Y')})"


def menu_item_attributes(
    item: dict[str, Any], *, show_weekday: bool = False
) -> dict[str, str]:
    """Build title, markdown and plain description for a menu day."""
    day: dt.date = item["date"]
    markdown = item.get("markdown")
    if not markdown:
        raw = item.get("summary") or item.get("description", "")
        markdown = format_menu_markdown(raw)

    return {
        "title": menu_title(day, show_weekday=show_weekday),
        "markdown": markdown,
        "description": item.get("description") or item.get("summary", ""),
    }


def entry_display_options(hass, entry_id: str) -> dict[str, bool]:
    """Read per-entry UI options stored in hass.data."""
    from .const import (
        DEFAULT_MENU_TODAY_FALLBACK,
        DEFAULT_TITLE_SHOW_WEEKDAY,
        DOMAIN,
    )

    data = hass.data.get(DOMAIN, {}).get(entry_id, {})
    return {
        "title_show_weekday": bool(
            data.get("title_show_weekday", DEFAULT_TITLE_SHOW_WEEKDAY)
        ),
        "menu_today_fallback": bool(
            data.get("menu_today_fallback", DEFAULT_MENU_TODAY_FALLBACK)
        ),
    }


def option_labels(items: list[dict[str, Any]]) -> list[str]:
    days = sorted(items_by_date(items))
    return [date_label(day) for day in days]


def parse_weeks_range(raw: str) -> tuple[int, int]:
    """Parse weeks range ``wstecz-naprzód``, e.g. ``1-4``."""
    text = raw.strip().replace(" ", "")
    if "-" not in text:
        raise ValueError(f"Invalid weeks range: {raw}")
    back_s, ahead_s = text.split("-", 1)
    back, ahead = int(back_s), int(ahead_s)
    if not (0 <= back <= 12 and 0 <= ahead <= 12):
        raise ValueError(f"Weeks out of range: {raw}")
    return back, ahead


def weeks_range_from_options(options: dict) -> tuple[int, int]:
    """Read weeks back/ahead from integration options (with legacy keys)."""
    from .const import (
        CONF_WEEKS_AHEAD,
        CONF_WEEKS_BACK,
        CONF_WEEKS_RANGE,
        DEFAULT_WEEKS_AHEAD,
        DEFAULT_WEEKS_BACK,
        DEFAULT_WEEKS_RANGE,
    )

    if raw := options.get(CONF_WEEKS_RANGE):
        try:
            return parse_weeks_range(str(raw))
        except ValueError:
            pass
    return (
        int(options.get(CONF_WEEKS_BACK, DEFAULT_WEEKS_BACK)),
        int(options.get(CONF_WEEKS_AHEAD, DEFAULT_WEEKS_AHEAD)),
    )


def format_weeks_range(back: int, ahead: int) -> str:
    return f"{back}-{ahead}"


def options_weeks_range_default(options: dict) -> str:
    from .const import CONF_WEEKS_RANGE, DEFAULT_WEEKS_RANGE

    if raw := options.get(CONF_WEEKS_RANGE):
        return str(raw)
    back, ahead = weeks_range_from_options(options)
    return format_weeks_range(back, ahead)