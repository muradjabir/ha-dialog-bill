"""Diagnostics support for Dialog Bill integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MOBILE_NUMBER,
    CONF_SELECTED_CONNECTIONS,
    CONF_SESSION_COOKIES,
    CONF_SESSION_DATA_KEY,
    DOMAIN,
)
from .coordinator import DialogDataUpdateCoordinator

TO_REDACT = {
    CONF_MOBILE_NUMBER,
    CONF_SELECTED_CONNECTIONS,
    CONF_SESSION_COOKIES,
    CONF_SESSION_DATA_KEY,
    "address",
    "connection",
    "cookies",
    "JSESSIONID",
    "mobile_number",
    "nickName",
    "selected_connections",
    "self_token",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: DialogDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    data: dict[str, Any] = {}
    if isinstance(coordinator.data, dict):
        for idx, conn_data in enumerate(coordinator.data.values(), 1):
            data[f"connection_{idx}"] = async_redact_data(conn_data, TO_REDACT)
    elif coordinator.data is not None:
        data = async_redact_data(coordinator.data, TO_REDACT)

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": data,
    }

