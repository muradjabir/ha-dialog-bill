"""Diagnostics support for Dialog Bill integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MOBILE_NUMBER,
    CONF_SESSION_COOKIES,
    CONF_SESSION_DATA_KEY,
    DOMAIN,
)
from .coordinator import DialogDataUpdateCoordinator

TO_REDACT = {
    CONF_MOBILE_NUMBER,
    CONF_SESSION_COOKIES,
    CONF_SESSION_DATA_KEY,
    "address",
    "self_token",
    "JSESSIONID",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: DialogDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(coordinator.data, TO_REDACT),
    }
