"""Register the Lovelace card for EduPage menu."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN, JS_CARD_FILENAME, JS_CARD_VERSION, URL_BASE

_LOGGER = logging.getLogger(__name__)


class JSModuleRegistration:
    """Register EduPage menu Lovelace card as a JS module."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.lovelace = self.hass.data.get("lovelace")

    async def async_register(self) -> None:
        """Serve static files and add the Lovelace resource when needed."""
        await self._async_register_path()
        mode = getattr(self.lovelace, "mode", None) or getattr(
            self.lovelace, "resource_mode", "yaml"
        )
        if mode == "storage":
            await self._async_wait_for_lovelace_resources()

    async def _async_register_path(self) -> None:
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, Path(__file__).parent, False)]
            )
        except RuntimeError:
            _LOGGER.debug("Static path %s already registered", URL_BASE)

    async def _async_wait_for_lovelace_resources(self) -> None:
        async def _check_loaded(_now: Any) -> None:
            if self.lovelace is None:
                self.lovelace = self.hass.data.get("lovelace")
            if self.lovelace and getattr(self.lovelace.resources, "loaded", False):
                await self._async_register_module()
            else:
                async_call_later(self.hass, 5, _check_loaded)

        await _check_loaded(0)

    async def _async_register_module(self) -> None:
        url = f"{URL_BASE}/{JS_CARD_FILENAME}"
        versioned_url = f"{url}?v={JS_CARD_VERSION}"
        existing = [
            resource
            for resource in self.lovelace.resources.async_items()
            if resource["url"].startswith(url)
        ]
        if existing:
            resource = existing[0]
            if resource["url"] != versioned_url:
                await self.lovelace.resources.async_update_item(
                    resource["id"],
                    {"res_type": "module", "url": versioned_url},
                )
            return

        _LOGGER.info("Registering Lovelace card: Jadłospis dnia")
        await self.lovelace.resources.async_create_item(
            {"res_type": "module", "url": versioned_url}
        )