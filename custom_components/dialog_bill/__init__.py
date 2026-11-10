"""The Dialog Bill integration."""

from __future__ import annotations

import logging

from aiohttp import CookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import DialogApiClient
from .const import CONF_MOBILE_NUMBER, CONF_SESSION_COOKIES, DOMAIN
from .coordinator import DialogDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dialog Bill from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_create_clientsession(
        hass,
        cookie_jar=CookieJar(unsafe=True),
    )
    cookies = entry.data.get(CONF_SESSION_COOKIES, {})
    mobile_number = entry.data.get(CONF_MOBILE_NUMBER)

    client = DialogApiClient(
        session=session,
        cookies=cookies,
        mobile_number=mobile_number,
    )

    coordinator = DialogDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok

