"""Config flow for Dialog Bill integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DialogApiClient, DialogApiError, DialogAuthError
from .const import (
    AUTH_METHOD_COOKIE,
    AUTH_METHOD_OTP,
    CONF_AUTH_METHOD,
    CONF_MOBILE_NUMBER,
    CONF_SCAN_INTERVAL,
    CONF_SELECTED_CONNECTIONS,
    CONF_SESSION_COOKIES,
    CONF_SESSION_DATA_KEY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class DialogConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dialog Bill."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._auth_data: dict[str, Any] = {}
        self._login_state: dict[str, Any] = {}
        self._discovered_connections: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return DialogOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step (enter mobile number for OTP login)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            auth_method = user_input.get(CONF_AUTH_METHOD, AUTH_METHOD_OTP)

            if auth_method == AUTH_METHOD_OTP:
                mobile = user_input.get(CONF_MOBILE_NUMBER, "").strip()
                if not mobile:
                    errors[CONF_MOBILE_NUMBER] = "empty_mobile"
                else:
                    client = DialogApiClient(session=session)
                    try:
                        self._login_state = await client.async_start_login(mobile)
                        self._auth_data = {
                            CONF_AUTH_METHOD: AUTH_METHOD_OTP,
                            CONF_MOBILE_NUMBER: self._login_state["mobile_number"],
                            CONF_SESSION_DATA_KEY: self._login_state["session_data_key"],
                            CONF_SESSION_COOKIES: self._login_state["cookies"],
                            CONF_SCAN_INTERVAL: user_input.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                            ),
                        }
                        return await self.async_step_otp()
                    except DialogAuthError:
                        errors["base"] = "invalid_mobile"
                    except DialogApiError:
                        errors["base"] = "cannot_connect"
                    except Exception as err:
                        _LOGGER.exception("Unexpected error during Dialog OTP request: %s", err)
                        errors["base"] = "unknown"

            else:  # Manual cookie method
                raw_cookie = user_input.get(CONF_SESSION_COOKIES, "").strip()
                cookies: dict[str, str] = {}
                for part in raw_cookie.split(";"):
                    if "=" in part:
                        k, v = part.strip().split("=", 1)
                        cookies[k] = v

                client = DialogApiClient(session=session, cookies=cookies)
                try:
                    conns = await client.async_get_connections()
                    if not conns:
                        errors["base"] = "no_connections"
                    else:
                        self._discovered_connections = conns
                        self._auth_data = {
                            CONF_AUTH_METHOD: AUTH_METHOD_COOKIE,
                            CONF_MOBILE_NUMBER: user_input.get(CONF_MOBILE_NUMBER, "Dialog Account"),
                            CONF_SESSION_COOKIES: cookies,
                            CONF_SCAN_INTERVAL: user_input.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                            ),
                        }
                        return await self.async_step_connections()
                except DialogAuthError:
                    errors["base"] = "invalid_auth"
                except DialogApiError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AUTH_METHOD, default=AUTH_METHOD_OTP
                ): vol.In(
                    {
                        AUTH_METHOD_OTP: "SMS OTP Login (Recommended)",
                        AUTH_METHOD_COOKIE: "Direct Session Cookie (Manual)",
                    }
                ),
                vol.Required(CONF_MOBILE_NUMBER, default=""): str,
                vol.Optional(CONF_SESSION_COOKIES, default=""): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle OTP submission."""
        errors: dict[str, str] = {}

        if user_input is not None:
            otp = user_input.get("otp", "").strip()
            session = async_get_clientsession(self.hass)
            client = DialogApiClient(
                session=session,
                cookies=self._login_state.get("cookies", {}),
                mobile_number=self._auth_data.get(CONF_MOBILE_NUMBER),
            )

            try:
                verified_cookies = await client.async_verify_otp(
                    session_data_key=self._login_state["session_data_key"],
                    otp=otp,
                    referer_url=self._login_state.get("referer_url"),
                )
                self._auth_data[CONF_SESSION_COOKIES] = verified_cookies

                # Discover connections
                conns = await client.async_get_connections()
                self._discovered_connections = conns

                if not conns:
                    # Single connection fallback to mobile number
                    mobile = self._auth_data[CONF_MOBILE_NUMBER]
                    await self.async_set_unique_id(mobile)
                    self._abort_if_unique_id_configured()
                    self._auth_data[CONF_SELECTED_CONNECTIONS] = [mobile]
                    return self.async_create_entry(
                        title=f"Dialog ({mobile})",
                        data=self._auth_data,
                    )

                if len(conns) == 1:
                    first = conns[0]
                    c_num = str(first.get("connection"))
                    await self.async_set_unique_id(c_num)
                    self._abort_if_unique_id_configured()
                    self._auth_data[CONF_SELECTED_CONNECTIONS] = [c_num]
                    return self.async_create_entry(
                        title=f"Dialog ({c_num})",
                        data=self._auth_data,
                    )

                return await self.async_step_connections()

            except DialogAuthError:
                errors["base"] = "invalid_otp"
            except DialogApiError:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error verifying Dialog OTP: %s", err)
                errors["base"] = "unknown"

        mobile_masked = self._auth_data.get(CONF_MOBILE_NUMBER, "")
        schema = vol.Schema(
            {
                vol.Required("otp"): str,
            }
        )

        return self.async_show_form(
            step_id="otp",
            data_schema=schema,
            errors=errors,
            description_placeholders={"mobile": mobile_masked},
        )

    async def async_step_connections(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select which connections to track."""
        errors: dict[str, str] = {}

        options: dict[str, str] = {}
        for c in self._discovered_connections:
            num = str(c.get("connection", "")).strip()
            nick = c.get("nickName") or num
            c_type = c.get("connectionType", "POSTPAID")
            lob = c.get("drupalLob") or c.get("ddsLob") or "GSM"
            options[num] = f"{nick} ({lob} {c_type} - {num})"

        if not options and self._auth_data.get(CONF_MOBILE_NUMBER):
            mobile = self._auth_data[CONF_MOBILE_NUMBER]
            options[mobile] = f"Mobile ({mobile})"

        if user_input is not None:
            selected = user_input.get(CONF_SELECTED_CONNECTIONS, [])
            if not selected:
                errors[CONF_SELECTED_CONNECTIONS] = "must_select_connection"
            else:
                self._auth_data[CONF_SELECTED_CONNECTIONS] = selected
                primary_id = selected[0]
                await self.async_set_unique_id(primary_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Dialog ({primary_id})",
                    data=self._auth_data,
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_CONNECTIONS,
                    default=list(options.keys()),
                ): cv.multi_select(options),
            }
        )

        return self.async_show_form(
            step_id="connections", data_schema=schema, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle re-authentication triggered when a session eventually expires."""
        mobile = entry_data.get(CONF_MOBILE_NUMBER, "")
        session = async_get_clientsession(self.hass)
        client = DialogApiClient(session=session)

        try:
            self._login_state = await client.async_start_login(mobile)
            self._auth_data = dict(entry_data)
            self._auth_data[CONF_SESSION_DATA_KEY] = self._login_state["session_data_key"]
            self._auth_data[CONF_SESSION_COOKIES] = self._login_state["cookies"]
            return await self.async_step_reauth_confirm()
        except Exception as err:
            _LOGGER.exception("Failed to initiate Dialog reauth: %s", err)
            return self.async_abort(reason="cannot_connect")

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm re-authentication with new OTP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            otp = user_input.get("otp", "").strip()
            session = async_get_clientsession(self.hass)
            client = DialogApiClient(
                session=session,
                cookies=self._login_state.get("cookies", {}),
                mobile_number=self._auth_data.get(CONF_MOBILE_NUMBER),
            )

            try:
                verified_cookies = await client.async_verify_otp(
                    session_data_key=self._login_state["session_data_key"],
                    otp=otp,
                    referer_url=self._login_state.get("referer_url"),
                )
                reauth_entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_SESSION_COOKIES: verified_cookies},
                )
            except DialogAuthError:
                errors["base"] = "invalid_otp"
            except Exception:
                errors["base"] = "cannot_connect"

        schema = vol.Schema({vol.Required("otp"): str})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"mobile": self._auth_data.get(CONF_MOBILE_NUMBER, "")},
        )


class DialogOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Dialog Bill integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_selected = self.config_entry.options.get(
            CONF_SELECTED_CONNECTIONS,
            self.config_entry.data.get(CONF_SELECTED_CONNECTIONS, []),
        )

        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        conn_options: dict[str, str] = {}
        if coordinator and coordinator.data:
            for c_num, c_data in coordinator.data.items():
                nick = c_data.get("nickName") or c_num
                c_type = c_data.get("connectionType") or c_data.get("connection_type") or "POSTPAID"
                conn_options[c_num] = f"{nick} ({c_type} - {c_num})"
        for c_num in current_selected:
            if c_num not in conn_options:
                conn_options[c_num] = str(c_num)

        schema_dict: dict[Any, Any] = {
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=current_interval,
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
        }
        if conn_options:
            schema_dict[
                vol.Required(
                    CONF_SELECTED_CONNECTIONS,
                    default=current_selected or list(conn_options.keys()),
                )
            ] = cv.multi_select(conn_options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )


class NoConnectionsFound(HomeAssistantError):
    """Error to indicate no connections found for this account."""

