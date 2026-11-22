from __future__ import annotations

import datetime as dt
import hashlib
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .menu_format import format_menu_description
from .const import CONF_URL, DOMAIN
from .menu_helpers import entry_display_options, menu_title

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EduPage menu calendar entity from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EdupageMenuCalendar(
                data["coordinator"],
                data["name"],
                entry.entry_id,
                entry.data[CONF_URL],
            )
        ],
        True,
    )


class EdupageMenuCalendar(CoordinatorEntity, CalendarEntity):
    """Calendar entity representing school lunch menu."""

    _attr_has_entity_name = True
    _attr_translation_key = "calendar"

    def __init__(self, coordinator, name: str, entry_id: str, url: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="EduPage",
            configuration_url=url,
        )

    def _build_event(self, item: dict[str, Any]) -> CalendarEvent:
        day: dt.date = item["date"]
        menu_text = item.get("description") or format_menu_description(
            item.get("summary", "")
        )
        opts = entry_display_options(self.hass, self._entry_id)
        title = menu_title(day, show_weekday=opts["title_show_weekday"])
        uid = hashlib.sha256(day.isoformat().encode()).hexdigest()[:16]

        return CalendarEvent(
            uid=uid,
            summary=title,
            start=day,
            end=day + dt.timedelta(days=1),
            description=menu_text,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming or current all-day event."""
        today = dt_util.now().date()
        for item in sorted(self.coordinator.data or [], key=lambda x: x["date"]):
            ev = self._build_event(item)
            if ev.end > today:
                return ev
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: dt.datetime,
        end_date: dt.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        range_start = dt_util.as_local(start_date).date()
        range_end = dt_util.as_local(end_date).date()
        result: list[CalendarEvent] = []

        for item in sorted(self.coordinator.data or [], key=lambda x: x["date"]):
            try:
                ev = self._build_event(item)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Nie udało się utworzyć wydarzenia kalendarza dla %s", item)
                continue

            event_start = (
                ev.start if isinstance(ev.start, dt.date) else ev.start.date()
            )
            event_end = ev.end if isinstance(ev.end, dt.date) else ev.end.date()
            if event_start < range_end and event_end > range_start:
                result.append(ev)

        _LOGGER.debug(
            "Zwracam %d wydarzeń jadłospisu (zakres %s–%s)",
            len(result),
            range_start,
            range_end,
        )
        return result

    async def async_added_to_hass(self) -> None:
        """Log cache size when the entity is ready."""
        await super().async_added_to_hass()
        count = len(self.coordinator.data or [])
        _LOGGER.info("Kalendarz jadłospisu: %d dni w pamięci podręcznej", count)
        if count == 0:
            await self.coordinator.async_request_refresh()