from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_URL, DOMAIN
from .menu_helpers import (
    date_label,
    default_menu_date,
    entry_display_options,
    items_by_date,
    label_to_date,
    menu_item_attributes,
    option_labels,
)

SIGNAL_SELECTED = f"{DOMAIN}_selected_{{entry_id}}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up day picker for the menu."""
    data = hass.data[DOMAIN][entry.entry_id]
    entity = EdupageMenuDaySelect(
        data["coordinator"],
        data["name"],
        entry.entry_id,
        entry.data[CONF_URL],
    )
    async_add_entities([entity])


class EdupageMenuDaySelect(RestoreEntity, CoordinatorEntity, SelectEntity):
    """Select which school-menu day to show on the dashboard."""

    _attr_has_entity_name = True
    _attr_translation_key = "day_picker"
    _attr_icon = "mdi:calendar-edit"

    def __init__(self, coordinator, name: str, entry_id: str, url: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_day_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="EduPage",
            configuration_url=url,
        )
        self._selected_date: dt.date | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last selected day."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state not in (
            None,
            "unknown",
            "unavailable",
        ):
            restored = label_to_date(last.state, self.coordinator.data or [])
            if restored:
                self._selected_date = restored

        self._sync_default_selection()
        self._publish_selected_date()
        if self.entity_id:
            self.hass.data[DOMAIN][self._entry_id]["select_entity_id"] = self.entity_id

    def _sync_default_selection(self) -> None:
        items = self.coordinator.data or []
        if self._selected_date and self._selected_date in items_by_date(items):
            return
        self._selected_date = default_menu_date(items)

    def _publish_selected_date(self) -> None:
        self.hass.data[DOMAIN][self._entry_id]["selected_date"] = self._selected_date

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync_default_selection()
        self._publish_selected_date()
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        return option_labels(self.coordinator.data or [])

    @property
    def current_option(self) -> str | None:
        if self._selected_date is None:
            return None
        return date_label(self._selected_date)

    @property
    def available(self) -> bool:
        return bool(self.options)

    async def async_select_option(self, option: str) -> None:
        picked = label_to_date(option, self.coordinator.data or [])
        if picked is None:
            return
        self._selected_date = picked
        self._publish_selected_date()
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            SIGNAL_SELECTED.format(entry_id=self._entry_id),
            {"option": option, "date": picked.isoformat()},
        )

    def _menu_item(self) -> dict[str, Any] | None:
        if self._selected_date is None:
            return None
        return items_by_date(self.coordinator.data or []).get(self._selected_date)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._menu_item()
        if item is None:
            return {}
        opts = entry_display_options(self.hass, self._entry_id)
        attrs = menu_item_attributes(item, show_weekday=opts["title_show_weekday"])
        attrs["date"] = self._selected_date.isoformat()
        return attrs