from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_URL, DOMAIN
from .menu_helpers import (
    entry_display_options,
    items_by_date,
    label_to_date,
    menu_item_attributes,
    next_menu_date,
    resolve_today_menu_date,
)
from .select import SIGNAL_SELECTED

DAY_SIGNAL = SIGNAL_SELECTED
SELECT_UNIQUE_SUFFIX = "_day_select"


class MidnightRefreshMixin:
    """Refresh entity state when the local calendar day changes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._unsub_midnight: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_midnight()
        self.async_on_remove(self._cancel_midnight)

    @callback
    def _schedule_midnight(self) -> None:
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None

        @callback
        def _at_midnight(_now: dt.datetime) -> None:
            self.async_write_ha_state()
            self._schedule_midnight()

        next_midnight = dt_util.start_of_local_day() + dt.timedelta(days=1)
        self._unsub_midnight = async_track_point_in_time(
            self.hass, _at_midnight, next_midnight
        )

    @callback
    def _cancel_midnight(self) -> None:
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up menu sensors for dashboards."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EdupageMenuListSensor(
                data["coordinator"],
                data["name"],
                entry.entry_id,
                entry.data[CONF_URL],
            ),
            EdupageMenuDaySensor(
                data["coordinator"],
                data["name"],
                entry.entry_id,
                entry.data[CONF_URL],
            ),
            EdupageMenuNextSensor(
                data["coordinator"],
                data["name"],
                entry.entry_id,
                entry.data[CONF_URL],
            ),
        ],
        update_before_add=True,
    )


class EdupageMenuListSensor(MidnightRefreshMixin, CoordinatorEntity, SensorEntity):
    """Today's (or next) menu — quick Markdown snapshot."""

    _attr_has_entity_name = True
    _attr_translation_key = "menu_today"
    _attr_icon = "mdi:food"

    def __init__(self, coordinator, name: str, entry_id: str, url: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_menu_today"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="EduPage",
            configuration_url=url,
        )

    def _item(self) -> dict[str, Any] | None:
        items = self.coordinator.data or []
        if (day := self._resolved_day(items)) is None:
            return None
        return items_by_date(items).get(day)

    def _resolved_day(self, items: list[dict[str, Any]]) -> dt.date | None:
        opts = entry_display_options(self.hass, self._entry_id)
        return resolve_today_menu_date(
            items, fallback_next=opts["menu_today_fallback"]
        )

    def _menu_attrs(self, item: dict[str, Any]) -> dict[str, Any]:
        opts = entry_display_options(self.hass, self._entry_id)
        attrs = menu_item_attributes(item, show_weekday=opts["title_show_weekday"])
        attrs["menu_source"] = "today"
        attrs["date"] = item["date"].isoformat()
        attrs["title_show_weekday"] = opts["title_show_weekday"]
        return attrs

    @property
    def native_value(self) -> str | None:
        item = self._item()
        return item["date"].isoformat() if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item()
        return self._menu_attrs(item) if item else {}


class EdupageMenuNextSensor(MidnightRefreshMixin, CoordinatorEntity, SensorEntity):
    """Next school day's menu (Fri/Sat/Sun → Monday)."""

    _attr_has_entity_name = True
    _attr_translation_key = "menu_next"
    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(self, coordinator, name: str, entry_id: str, url: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_menu_next"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="EduPage",
            configuration_url=url,
        )

    def _resolved_day(self, items: list[dict[str, Any]]) -> dt.date | None:
        return next_menu_date(items)

    def _item(self) -> dict[str, Any] | None:
        items = self.coordinator.data or []
        if (day := self._resolved_day(items)) is None:
            return None
        return items_by_date(items).get(day)

    @property
    def native_value(self) -> str | None:
        item = self._item()
        return item["date"].isoformat() if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item()
        if item is None:
            return {}
        opts = entry_display_options(self.hass, self._entry_id)
        attrs = menu_item_attributes(item, show_weekday=opts["title_show_weekday"])
        attrs["menu_source"] = "next_school_day"
        attrs["date"] = item["date"].isoformat()
        attrs["title_show_weekday"] = opts["title_show_weekday"]
        return attrs


class EdupageMenuDaySensor(CoordinatorEntity, SensorEntity):
    """Menu for the day chosen on the select entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "menu_picked"
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(self, coordinator, name: str, entry_id: str, url: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_menu_day"
        self._select_entity_id: str | None = None
        self._select_track_attached = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="EduPage",
            configuration_url=url,
        )

    def _resolve_select_entity_id(self) -> str | None:
        if self._select_entity_id:
            return self._select_entity_id

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        if stored := entry_data.get("select_entity_id"):
            self._select_entity_id = stored
            return stored

        entity_id = er.async_get(self.hass).async_get_entity_id(
            "select",
            DOMAIN,
            f"{self._entry_id}{SELECT_UNIQUE_SUFFIX}",
        )
        if entity_id:
            self._select_entity_id = entity_id
        return entity_id

    def _selected_date(self) -> dt.date | None:
        items = self.coordinator.data or []
        select_id = self._resolve_select_entity_id()
        if select_id and (state := self.hass.states.get(select_id)):
            if state.state not in (None, "unknown", "unavailable", ""):
                if parsed := label_to_date(state.state, items):
                    return parsed

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        stored = entry_data.get("selected_date")
        if isinstance(stored, dt.date):
            return stored
        return None

    def _selected_item(self) -> dict[str, Any] | None:
        day = self._selected_date()
        if day is None:
            return None
        return items_by_date(self.coordinator.data or {}).get(day)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                DAY_SIGNAL.format(entry_id=self._entry_id),
                self.async_write_ha_state,
            )
        )
        self._attach_select_listener()

    @callback
    def _attach_select_listener(self) -> None:
        if self._select_track_attached:
            return
        if not (select_id := self._resolve_select_entity_id()):
            return
        self._select_track_attached = True
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [select_id], self._on_select_state_changed
            )
        )

    @callback
    def _on_select_state_changed(self, event) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        item = self._selected_item()
        return item["date"].isoformat() if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._selected_item()
        if item is None:
            return {}
        opts = entry_display_options(self.hass, self._entry_id)
        attrs = menu_item_attributes(item, show_weekday=opts["title_show_weekday"])
        attrs["menu_source"] = "picked"
        attrs["title_show_weekday"] = opts["title_show_weekday"]
        if day := self._selected_date():
            attrs["date"] = day.isoformat()
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        self._attach_select_listener()
        self.async_write_ha_state()