"""DataUpdateCoordinator for Dialog Bill."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DialogApiClient, DialogApiError, DialogAuthError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SELECTED_CONNECTIONS,
    CONF_SESSION_COOKIES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class DialogDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Class to manage fetching Dialog billing and connection data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DialogApiClient,
    ) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.client = client
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from Dialog API."""
        try:
            # 1. Discover or refresh connection list
            raw_connections = await self.client.async_get_connections()
            available_conns = {str(c.get("connection")): c for c in raw_connections if c.get("connection")}

            # Selected connections from options or data, or all discovered
            selected: list[str] = (
                self.entry.options.get(CONF_SELECTED_CONNECTIONS)
                or self.entry.data.get(CONF_SELECTED_CONNECTIONS)
                or list(available_conns.keys())
            )

            results: dict[str, dict[str, Any]] = {}
            for conn_num in selected:
                if not conn_num:
                    continue
                conn_data = await self.client.async_get_connection_data(conn_num)
                # Merge base connection metadata (nickname, isPrimary, LOB)
                if conn_num in available_conns:
                    meta = available_conns[conn_num]
                    conn_data["nickName"] = meta.get("nickName") or meta.get("connection")
                    conn_data["isPrimary"] = meta.get("isPrimary", False)
                    c_type = str(
                        meta.get("connectionType")
                        or conn_data.get("connection_type")
                        or "POSTPAID"
                    ).upper()
                    conn_data["connectionType"] = c_type
                    conn_data["connection_type"] = c_type
                    conn_data["drupalLob"] = meta.get("drupalLob") or conn_data.get("lob") or "GSM"
                    conn_data["ddsLob"] = meta.get("ddsLob") or conn_data.get("lob") or "GSM"
                results[conn_num] = conn_data

            # 2. Dynamic sliding session persistence:
            # If Dialog server returned updated Set-Cookie headers, persist them to entry.data!
            if self.client.cookies_updated:
                _LOGGER.debug("Dialog session cookie renewed by server, updating config entry")
                new_data = dict(self.entry.data)
                new_data[CONF_SESSION_COOKIES] = self.client.cookies
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)
                self.client.cookies_updated = False

            return results

        except DialogAuthError as err:
            _LOGGER.warning("Dialog session has expired: %s", err)
            self.entry.async_start_reauth(self.hass)
            raise ConfigEntryAuthFailed(err) from err
        except DialogApiError as err:
            raise UpdateFailed(f"Dialog API error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating Dialog data: {err}") from err

