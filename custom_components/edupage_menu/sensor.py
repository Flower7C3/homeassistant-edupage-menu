from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_URL, DOMAIN
from .menu_helpers import (
    default_menu_date,
    items_by_date,
    label_to_date,
    menu_item_attributes,
)
from .select import SIGNAL_SELECTED

DAY_SIGNAL = SIGNAL_SELECTED
SELECT_UNIQUE_SUFFIX = "_day_select"


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
        ],
    )


class EdupageMenuListSensor(CoordinatorEntity, SensorEntity):
    """Today's (or next) menu — quick Markdown snapshot."""

    _attr_has_entity_name = True
    _attr_translation_key = "menu_today"
    _attr_icon = "mdi:food"

    def __init__(self, coordinator, name: str, entry_id: str, url: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_menu_today"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="EduPage",
            configuration_url=url,
        )

    def _item(self) -> dict[str, Any] | None:
        items = self.coordinator.data or []
        day = default_menu_date(items)
        if day is None:
            return None
        return items_by_date(items).get(day)

    @property
    def native_value(self) -> str | None:
        item = self._item()
        return item["date"].isoformat() if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item()
        return menu_item_attributes(item) if item else {}


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
        attrs = menu_item_attributes(item)
        if day := self._selected_date():
            attrs["date"] = day.isoformat()
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        self._attach_select_listener()
        self.async_write_ha_state()