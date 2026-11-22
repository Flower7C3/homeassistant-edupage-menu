"""Register the Lovelace card for EduPage menu."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN, JS_CARD_FILENAME, JS_CARD_VERSION, URL_BASE

_LOGGER = logging.getLogger(__name__)

_YAML_RESOURCE_HINT = (
    "Karta Lovelace „edupage-menu-day” wymaga zasobu JS. "
    "Dodaj w panelu Lovelace → Zasoby (typ: Moduł JavaScript): "
    "%s/%s?v=%s"
)


def _lovelace(hass: HomeAssistant) -> Any | None:
    return hass.data.get("lovelace")


def _resource_mode(hass: HomeAssistant) -> str:
    lc = _lovelace(hass)
    if lc is None:
        return "yaml"
    if hasattr(lc, "resource_mode"):
        return lc.resource_mode
    if hasattr(lc, "mode"):
        return lc.mode
    if isinstance(lc, dict):
        return lc.get("mode", "yaml")
    return "yaml"


def _resources(hass: HomeAssistant) -> Any | None:
    lc = _lovelace(hass)
    if lc is None:
        return None
    if hasattr(lc, "resources"):
        return lc.resources
    if isinstance(lc, dict):
        return lc.get("resources")
    return None


class JSModuleRegistration:
    """Register EduPage menu Lovelace card as a JS module."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._resource_registered = False
        self._yaml_hint_logged = False

    async def async_register(self) -> None:
        """Serve static files and add the Lovelace resource when needed."""
        await self._async_register_path()
        if _resource_mode(self.hass) == "storage":
            await self._async_wait_for_lovelace_resources()
        else:
            self._log_yaml_resource_hint()

    async def _async_register_path(self) -> None:
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, Path(__file__).parent, False)]
            )
            _LOGGER.debug("Registered EduPage menu card path at %s", URL_BASE)
        except RuntimeError:
            _LOGGER.debug("Static path %s already registered", URL_BASE)

    def _log_yaml_resource_hint(self) -> None:
        if self._yaml_hint_logged:
            return
        self._yaml_hint_logged = True
        _LOGGER.warning(
            _YAML_RESOURCE_HINT,
            URL_BASE,
            JS_CARD_FILENAME,
            JS_CARD_VERSION,
        )

    async def _async_wait_for_lovelace_resources(self) -> None:
        @callback
        def _on_component_loaded(event) -> None:
            if event.data.get("component") == "lovelace":
                self.hass.async_create_task(self._async_wait_for_lovelace_resources())

        if "lovelace" not in self.hass.config.components:
            self.hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, _on_component_loaded)

        async def _check_loaded(_now: Any) -> None:
            resources = _resources(self.hass)
            if resources and getattr(resources, "loaded", False):
                await self._async_register_module()
                return
            async_call_later(self.hass, 5, _check_loaded)

        await _check_loaded(0)

    async def _async_register_module(self) -> None:
        resources = _resources(self.hass)
        if resources is None:
            _LOGGER.debug("Lovelace resources not available yet")
            return
        if self._resource_registered:
            return

        url = f"{URL_BASE}/{JS_CARD_FILENAME}"
        versioned_url = f"{url}?v={JS_CARD_VERSION}"
        existing = [
            resource
            for resource in resources.async_items()
            if resource["url"].split("?")[0] == url
        ]
        if existing:
            resource = existing[0]
            if resource["url"] != versioned_url:
                await resources.async_update_item(
                    resource["id"],
                    {"res_type": "module", "url": versioned_url},
                )
            self._resource_registered = True
            return

        _LOGGER.info("Registering Lovelace card: Jadłospis dnia (%s)", versioned_url)
        await resources.async_create_item(
            {"res_type": "module", "url": versioned_url}
        )
        self._resource_registered = True