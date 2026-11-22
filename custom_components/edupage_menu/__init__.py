from __future__ import annotations

import datetime as dt
import json
import logging
import re
from typing import Any

from aiohttp import ClientError
from bs4 import BeautifulSoup

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    REQUEST_HEADERS,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR, Platform.SELECT]

DATE_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b"),
    re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"),
]

_EDUPAGE_CANTEEN_DAY_RE = re.compile(r"^__mt(\d{4}-\d{2}-\d{2})$")
_EDUPAGE_MENU_ITEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_CLOSED_MENU_LABELS = frozenset({"zamknięte", "zamkniete", "closed"})
_WEEKDAY_OPTION_RE = re.compile(
    r"^(Pon|Wt|Śr|Czw|Pt|So|Ni), \d{2}\.\d{2}\.\d{4}$"
)


def _parse_date(raw: str) -> dt.date | None:
    """Parse common date formats into a date object."""
    text = raw.strip()
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        token = match.group(1)
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(token, fmt).date()
            except ValueError:
                continue
    return None


def _clean_text(value: str) -> str:
    """Normalize whitespace and strip noise."""
    return re.sub(r"\s+", " ", value).strip()


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
        return _clean_text(stripped)
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
        return _clean_text(stripped)
    return "\n\n".join(_format_dish_markdown(line) for line in lines)


def _extract_from_json_blob(html: str) -> list[dict[str, Any]]:
    """Best-effort extraction of lunch/menu entries from embedded JS/JSON."""
    entries: list[dict[str, Any]] = []
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        content = script.string or ""
        if not any(k in content.lower() for k in ("lunch", "meal", "menu", "obiad", "zupa")):
            continue

        for match in re.finditer(r"\{[^{}]{20,15000}\}", content):
            blob = match.group(0)
            try:
                data = json.loads(blob)
            except (json.JSONDecodeError, ValueError):
                continue

            if isinstance(data, dict):
                _walk_json_for_meals(data, entries)

    return _dedupe_entries(entries)


def _walk_json_for_meals(
    node: Any, acc: list[dict[str, Any]], current_date: dt.date | None = None
) -> None:
    """Recursively scan JSON structures for date + meal descriptions."""
    if isinstance(node, dict):
        for k, v in node.items():
            parsed_key_date = _parse_date(str(k))
            if parsed_key_date and isinstance(v, (dict, list, str)):
                _walk_json_for_meals(v, acc, parsed_key_date)

        local_date = current_date
        for date_key in ("date", "day", "datum"):
            if date_key in node and node[date_key]:
                found = _parse_date(str(node[date_key]))
                if found:
                    local_date = found
                    break

        meal_texts: list[str] = []
        for meal_key in (
            "lunch",
            "lunches",
            "meal",
            "meals",
            "menu",
            "title",
            "name",
            "text",
            "description",
            "food",
        ):
            val = node.get(meal_key)
            if isinstance(val, str):
                cleaned = _clean_text(val)
                if len(cleaned) > 3 and not _parse_date(cleaned):
                    meal_texts.append(cleaned)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        cleaned = _clean_text(item)
                        if len(cleaned) > 2:
                            meal_texts.append(cleaned)
                    elif isinstance(item, dict):
                        _walk_json_for_meals(item, acc, local_date)

        if local_date and meal_texts:
            acc.append(
                {
                    "date": local_date,
                    "summary": " | ".join(dict.fromkeys(meal_texts)),
                }
            )

        for k, v in node.items():
            if k not in ("date", "day", "datum"):
                _walk_json_for_meals(v, acc, local_date)

    elif isinstance(node, list):
        for item in node:
            _walk_json_for_meals(item, acc, current_date)


def _list_item_id(tag) -> str:
    """Return EduPage list item id (BeautifulSoup lowercases data-* attributes)."""
    return str(tag.get("data-listitemid") or tag.get("data-listItemId") or "")


def _parse_edupage_menu_items(container) -> list[dict[str, Any]]:
    """Walk EduPage menu list items and pair day headers with meal rows."""
    entries: list[dict[str, Any]] = []
    current_date: dt.date | None = None

    for li in container.find_all("li"):
        list_item_id = _list_item_id(li)
        if not list_item_id:
            continue

        day_match = _EDUPAGE_CANTEEN_DAY_RE.match(list_item_id)
        if day_match:
            current_date = dt.datetime.strptime(day_match.group(1), "%Y-%m-%d").date()
            continue

        if current_date is None:
            continue

        if not _EDUPAGE_MENU_ITEM_RE.match(list_item_id):
            continue
        if not list_item_id.startswith(current_date.isoformat()):
            current_date = None
            continue

        raw_menu = li.get_text("\n", strip=True)
        raw_check = _clean_text(raw_menu)
        if len(raw_check) < 4 or raw_check.lower() in _CLOSED_MENU_LABELS:
            current_date = None
            continue

        entries.append(
            {
                "date": current_date,
                "description": format_menu_description(raw_menu),
                "markdown": format_menu_markdown(raw_menu),
                "summary": format_menu_description(raw_menu),
            }
        )
        current_date = None

    return entries


def _extract_from_edupage_canteen_menu(html: str) -> list[dict[str, Any]]:
    """Parse the public EduPage canteen menu widget (no login required)."""
    soup = BeautifulSoup(html, "html.parser")
    roots: list[Any] = []
    for node in soup.find_all(id=re.compile(r"menu_CanteenMenu", re.I)):
        roots.append(node)
    for node in soup.find_all(attrs={"data-sgid": re.compile(r"CanteenMenu", re.I)}):
        if node not in roots:
            roots.append(node)

    entries: list[dict[str, Any]] = []
    for root in roots:
        entries.extend(_parse_edupage_menu_items(root))

    if not entries:
        entries = _parse_edupage_menu_items(soup)

    return _dedupe_entries(entries)


def _extract_from_html(html: str) -> list[dict[str, Any]]:
    """Fallback HTML parser for tables or cards containing dates and menu text."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict[str, Any]] = []

    for row in soup.find_all(["tr", "article", "li", "div"]):
        text = _clean_text(row.get_text(" ", strip=True))
        if not text or len(text) > 600:
            continue

        parsed_date = _parse_date(text)
        if not parsed_date:
            continue

        description = _clean_text(
            re.sub(r"\b(\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})\b", "", text)
        )
        if len(description) < 4:
            continue

        entries.append(
            {
                "date": parsed_date,
                "summary": description,
            }
        )

    return _dedupe_entries(entries)


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate entries by date and summary."""
    seen: set[tuple[dt.date, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in sorted(entries, key=lambda x: x["date"]):
        text_key = item.get("description") or item.get("summary", "")
        key = (item["date"], text_key)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Prepare shared integration data."""
    hass.data.setdefault(DOMAIN, {})

    async def _register_after_start(_event=None) -> None:
        if hass.config_entries.async_entries(DOMAIN):
            await _async_register_frontend(hass)

    if hass.state == CoreState.running:
        await _register_after_start()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_after_start)
    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    from .frontend import JSModuleRegistration

    await JSModuleRegistration(hass).async_register()


def parse_menu_page(html: str) -> list[dict[str, Any]]:
    """Extract menu events from EduPage HTML."""
    edupage_entries = _extract_from_edupage_canteen_menu(html)
    if edupage_entries:
        return edupage_entries
    json_entries = _extract_from_json_blob(html)
    if json_entries:
        return json_entries
    return _extract_from_html(html)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EduPage Menu Calendar from a config entry."""
    url: str = entry.data[CONF_URL]
    name: str = entry.data.get(CONF_NAME, DEFAULT_NAME)
    raw_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    scan_interval = (
        raw_interval
        if isinstance(raw_interval, dt.timedelta)
        else dt.timedelta(seconds=int(raw_interval))
    )

    session = async_get_clientsession(hass)

    async def _async_update_data() -> list[dict[str, Any]]:
        try:
            async with session.get(url, timeout=20, headers=REQUEST_HEADERS) as resp:
                resp.raise_for_status()
                html = await resp.text()
        except (ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Błąd pobierania jadłospisu z {url}: {err}") from err

        events = await hass.async_add_executor_job(parse_menu_page, html)
        if events:
            _LOGGER.info("Pobrano %d wpisów jadłospisu z %s", len(events), url)
        else:
            _LOGGER.warning(
                "Nie znaleziono jadłospisu na stronie %s (len HTML=%d)",
                url,
                len(html),
            )
        return events

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{name}",
        update_method=_async_update_data,
        update_interval=scan_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        raise ConfigEntryNotReady(
            f"Nie udało się odczytać jadłospisu z {url} (odświeżenie za chwilę)"
        )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "name": name,
        "selected_date": None,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_frontend(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok