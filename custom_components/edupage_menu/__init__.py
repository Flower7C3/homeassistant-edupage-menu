from __future__ import annotations

import datetime as dt
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from aiohttp import ClientError
from bs4 import BeautifulSoup

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MENU_TODAY_FALLBACK,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_TITLE_SHOW_WEEKDAY,
    CONF_URL,
    DEFAULT_MENU_TODAY_FALLBACK,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TITLE_SHOW_WEEKDAY,
    DOMAIN,
    REQUEST_HEADERS,
)
from .menu_helpers import weeks_range_from_options

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
_EDUPAGE_WIDGET_ID_RE = re.compile(r"menu_CanteenMenu_\d+", re.I)


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


def _base_url_without_query(url: str) -> str:
    parsed = urlparse(url.strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _url_query_params(url: str) -> dict[str, str]:
    parsed = urlparse(url.strip())
    return {key: values[0] for key, values in parse_qs(parsed.query).items() if values}


def _detect_canteen_widget_id(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(id=_EDUPAGE_WIDGET_ID_RE):
        widget_id = node.get("id")
        if widget_id:
            return str(widget_id)
    for node in soup.find_all(attrs={"data-sgid": re.compile(r"CanteenMenu", re.I)}):
        sgid = str(node.get("data-sgid") or node.get("id") or "")
        if "CanteenMenu" in sgid:
            return sgid if sgid.startswith("menu_") else f"menu_{sgid}"
    return None


def build_menu_page_url(
    base_url: str,
    *,
    wid: str | None,
    anchor: dt.date | None,
) -> str:
    """Build EduPage menu URL with optional week navigation query params."""
    base = _base_url_without_query(base_url)
    params = _url_query_params(base_url)
    if wid:
        params["wid"] = wid
    elif anchor is not None:
        params.pop("date", None)
    if anchor is not None:
        params["date"] = anchor.isoformat()
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def _week_anchor_dates(weeks_back: int, weeks_ahead: int) -> list[dt.date]:
    """Dates to pass as EduPage `date=` — one per calendar week in the range."""
    today = dt_util.now().date()
    return [
        today + dt.timedelta(weeks=offset)
        for offset in range(-weeks_back, weeks_ahead + 1)
    ]


def _menu_page_urls(
    base_url: str,
    *,
    wid: str | None,
    weeks_back: int,
    weeks_ahead: int,
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for anchor in _week_anchor_dates(weeks_back, weeks_ahead):
        page_url = build_menu_page_url(base_url, wid=wid, anchor=anchor)
        if page_url not in seen:
            seen.add(page_url)
            ordered.append(page_url)
    return ordered


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
    weeks_back, weeks_ahead = weeks_range_from_options(entry.options)

    async def _fetch_html(page_url: str) -> str:
        async with session.get(page_url, timeout=20, headers=REQUEST_HEADERS) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def _async_update_data() -> list[dict[str, Any]]:
        widget_id = _url_query_params(url).get("wid")
        pages: dict[str, str] = {}

        try:
            pages[url] = await _fetch_html(url)
        except (ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Błąd pobierania jadłospisu z {url}: {err}") from err

        if not widget_id:
            widget_id = _detect_canteen_widget_id(pages[url])

        page_urls = _menu_page_urls(
            url,
            wid=widget_id,
            weeks_back=weeks_back,
            weeks_ahead=weeks_ahead,
        )

        for page_url in page_urls:
            if page_url in pages:
                continue
            try:
                pages[page_url] = await _fetch_html(page_url)
            except (ClientError, TimeoutError) as err:
                _LOGGER.warning("Pominięto tydzień jadłospisu (%s): %s", page_url, err)

        events: list[dict[str, Any]] = []
        for page_url, html in pages.items():
            week_events = await hass.async_add_executor_job(parse_menu_page, html)
            if week_events:
                events.extend(week_events)
            else:
                _LOGGER.debug("Brak jadłospisu na %s", page_url)

        events = _dedupe_entries(events)
        if events:
            _LOGGER.info(
                "Pobrano %d dni jadłospisu (%d stron, wid=%s)",
                len(events),
                len(pages),
                widget_id or "?",
            )
        else:
            _LOGGER.warning(
                "Nie znaleziono jadłospisu (źródło %s, %d stron)",
                url,
                len(pages),
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
        "title_show_weekday": entry.options.get(
            CONF_TITLE_SHOW_WEEKDAY, DEFAULT_TITLE_SHOW_WEEKDAY
        ),
        "menu_today_fallback": entry.options.get(
            CONF_MENU_TODAY_FALLBACK, DEFAULT_MENU_TODAY_FALLBACK
        ),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_ensure_menu_next_sensor(hass, entry)
    await _async_register_frontend(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_ensure_menu_next_sensor(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Register menu_next on upgrades without re-adding the integration."""
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_menu_next"
    if registry.async_get_entity_id("sensor", DOMAIN, unique_id):
        return

    _LOGGER.info("Brak encji menu_next — ponowne ładowanie platformy sensor")
    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        return
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Bump config entry version after entity additions."""
    if config_entry.version < 2:
        hass.config_entries.async_update_entry(config_entry, version=2)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok