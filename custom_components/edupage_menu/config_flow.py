from __future__ import annotations

from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import parse_menu_page
from .const import (
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_MENU_TODAY_FALLBACK,
    CONF_TITLE_SHOW_WEEKDAY,
    CONF_WEEKS_AHEAD,
    CONF_WEEKS_BACK,
    DEFAULT_MENU_TODAY_FALLBACK,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TITLE_SHOW_WEEKDAY,
    DEFAULT_URL,
    DEFAULT_WEEKS_AHEAD,
    DEFAULT_WEEKS_BACK,
    DOMAIN,
    REQUEST_HEADERS,
)


class EdupageMenuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EduPage Menu Calendar."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].strip()
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(url, timeout=15, headers=REQUEST_HEADERS) as resp:
                    if resp.status >= 400:
                        errors["base"] = "cannot_connect"
                    else:
                        html = await resp.text()
                        entries = await self.hass.async_add_executor_job(
                            parse_menu_page, html
                        )
                        if not entries:
                            errors["base"] = "no_menu"
            except (ClientError, TimeoutError):
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip() or DEFAULT_NAME,
                    data={
                        CONF_URL: url,
                        CONF_NAME: user_input[CONF_NAME].strip() or DEFAULT_NAME,
                    },
                    options={
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
                        ),
                        CONF_WEEKS_BACK: DEFAULT_WEEKS_BACK,
                        CONF_WEEKS_AHEAD: DEFAULT_WEEKS_AHEAD,
                        CONF_TITLE_SHOW_WEEKDAY: DEFAULT_TITLE_SHOW_WEEKDAY,
                        CONF_MENU_TODAY_FALLBACK: DEFAULT_MENU_TODAY_FALLBACK,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=DEFAULT_URL): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=int(DEFAULT_SCAN_INTERVAL.total_seconds()),
                ): vol.All(vol.Coerce(int), vol.Range(min=900, max=86400)),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return EdupageMenuOptionsFlow(config_entry)


class EdupageMenuOptionsFlow(config_entries.OptionsFlow):
    """Handle options for EduPage Menu Calendar."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        weeks_back = self._config_entry.options.get(
            CONF_WEEKS_BACK, DEFAULT_WEEKS_BACK
        )
        weeks_ahead = self._config_entry.options.get(
            CONF_WEEKS_AHEAD, DEFAULT_WEEKS_AHEAD
        )
        title_weekday = self._config_entry.options.get(
            CONF_TITLE_SHOW_WEEKDAY, DEFAULT_TITLE_SHOW_WEEKDAY
        )
        today_fallback = self._config_entry.options.get(
            CONF_MENU_TODAY_FALLBACK, DEFAULT_MENU_TODAY_FALLBACK
        )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current_interval,
                ): vol.All(vol.Coerce(int), vol.Range(min=900, max=86400)),
                vol.Optional(CONF_WEEKS_BACK, default=weeks_back): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=12)
                ),
                vol.Optional(CONF_WEEKS_AHEAD, default=weeks_ahead): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=12)
                ),
                vol.Optional(CONF_TITLE_SHOW_WEEKDAY, default=title_weekday): bool,
                vol.Optional(CONF_MENU_TODAY_FALLBACK, default=today_fallback): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)