"""API Client for Dialog Axiata (MyDialog & Dialog ID)."""

from __future__ import annotations

import logging
import re
from typing import Any
import urllib.parse

import aiohttp

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0"


class DialogAuthError(Exception):
    """Exception raised when authentication fails."""


class DialogApiError(Exception):
    """Exception raised when API calls fail."""


class DialogApiClient:
    """Dialog Axiata API Client supporting OTP login, sliding session refresh, and multi-connection discovery."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        cookies: dict[str, str] | None = None,
        mobile_number: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._cookies: dict[str, str] = dict(cookies or {})
        self._mobile_number = mobile_number
        self.cookies_updated = False

    @property
    def cookies(self) -> dict[str, str]:
        """Return the current session cookies."""
        return self._cookies

    def _extract_cookies(self, response: aiohttp.ClientResponse) -> None:
        """Extract and store cookies from the response for sliding session renewal."""
        if "Set-Cookie" in response.headers:
            for cookie in response.cookies.values():
                old_val = self._cookies.get(cookie.key)
                if old_val != cookie.value:
                    self._cookies[cookie.key] = cookie.value
                    self.cookies_updated = True

    async def async_start_login(self, mobile_number: str) -> dict[str, Any]:
        """Initiate Dialog ID SSO login and request SMS OTP.

        Returns a dictionary with 'session_data_key' and initial cookies.
        """
        clean_number = mobile_number.strip().replace(" ", "").replace("-", "")
        # Standardize format for Dialog ID: 0771234567 or 771234567
        if clean_number.startswith("+94"):
            clean_number = "0" + clean_number[3:]
        elif clean_number.startswith("94"):
            clean_number = "0" + clean_number[2:]
        elif len(clean_number) == 9 and clean_number.startswith("7"):
            clean_number = "0" + clean_number

        self._mobile_number = clean_number

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        # Step 1: Start SSO redirect chain
        start_url = "https://dialog.lk/sso-login?language=en&destination=L215ZGlhbG9nLXdlYj9sYW5ndWFnZT1lbg=="
        try:
            async with self._session.get(start_url, headers=headers, allow_redirects=True) as resp:
                self._extract_cookies(resp)
                html = await resp.text()
                final_url = str(resp.url)
        except Exception as err:
            raise DialogApiError(f"Failed to connect to Dialog SSO login: {err}") from err

        match = re.search(r'name=["\']sessionDataKey["\']\s+value=["\']([^"\']+)["\']', html)
        if not match:
            # Check if sessionDataKey is in URL query parameters
            query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
            if "sessionDataKey" in query:
                session_data_key = query["sessionDataKey"][0]
            else:
                raise DialogAuthError("Could not retrieve sessionDataKey from Dialog ID login page")
        else:
            session_data_key = match.group(1)

        # Step 2: Submit mobile number to trigger SMS OTP
        commonauth_url = "https://did.dialog.lk/commonauth"
        post_data = {
            "sessionDataKey": session_data_key,
            "msisdn": clean_number,
        }
        post_headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": final_url,
            "Origin": "https://did.dialog.lk",
        }

        try:
            async with self._session.post(
                commonauth_url,
                data=post_data,
                headers=post_headers,
                cookies=self._cookies,
                allow_redirects=True,
            ) as resp:
                self._extract_cookies(resp)
                otp_page_html = await resp.text()
                otp_final_url = str(resp.url)
        except Exception as err:
            raise DialogApiError(f"Failed to request OTP from Dialog ID: {err}") from err

        # Verify that OTP was sent
        if "otp" not in otp_page_html.lower() and "otp" not in otp_final_url.lower():
            if "invalid" in otp_page_html.lower():
                raise DialogAuthError("Invalid mobile number format for Dialog ID")
            raise DialogAuthError("Dialog ID did not return an OTP prompt page")

        # Extract any refreshed sessionDataKey for step 2
        sdk_match = re.search(r'name=["\']sessionDataKey["\']\s+id=["\']sessionDataKey["\']\s+value=["\']([^"\']+)["\']', otp_page_html)
        if sdk_match:
            session_data_key = sdk_match.group(1)

        return {
            "session_data_key": session_data_key,
            "cookies": self._cookies,
            "mobile_number": clean_number,
            "referer_url": otp_final_url,
        }

    async def async_verify_otp(
        self,
        session_data_key: str,
        otp: str,
        referer_url: str | None = None,
    ) -> dict[str, str]:
        """Submit the SMS OTP, complete Dialog ID authentication, and store the session cookies."""
        commonauth_url = "https://did.dialog.lk/commonauth"
        post_data = {
            "sessionDataKey": session_data_key,
            "otp": str(otp).strip(),
        }
        post_headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer_url or "https://did.dialog.lk/authenticationendpoint/login.do",
            "Origin": "https://did.dialog.lk",
        }

        try:
            async with self._session.post(
                commonauth_url,
                data=post_data,
                headers=post_headers,
                cookies=self._cookies,
                allow_redirects=True,
            ) as resp:
                self._extract_cookies(resp)
                final_html = await resp.text()
                final_url = str(resp.url)
        except Exception as err:
            raise DialogApiError(f"Failed to submit OTP to Dialog ID: {err}") from err

        # Check for errors in OTP submission
        if "invalid otp" in final_html.lower() or "incorrect" in final_html.lower():
            raise DialogAuthError("The OTP entered is incorrect or expired")

        # Ensure we acquired the Drupal session cookie
        has_ssess = any(k.startswith("SSESS") for k in self._cookies)
        if not has_ssess and "dialog.lk" not in final_url:
            raise DialogAuthError("Authentication succeeded but failed to acquire Dialog web session cookie")

        _LOGGER.debug("Dialog authentication successful, acquired session cookies")
        return self._cookies

    async def async_post_proxy(
        self,
        route: str,
        payload: dict[str, Any] | None = None,
        msisdn_header: str | None = None,
    ) -> dict[str, Any]:
        """Send an authenticated POST request to /selfcare-proxy?r=<route>."""
        url = f"https://dialog.lk/selfcare-proxy?r={route}"
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://dialog.lk",
            "Referer": "https://dialog.lk/mydialog-web",
        }
        if msisdn_header:
            headers["msisdn"] = str(msisdn_header)

        data = payload if payload is not None else {}

        try:
            async with self._session.post(
                url,
                json=data,
                headers=headers,
                cookies=self._cookies,
            ) as resp:
                self._extract_cookies(resp)
                if resp.status == 403:
                    body = await resp.text()
                    if "Token not found" in body or "Forbidden" in body:
                        raise DialogAuthError("Session expired or invalid. Please re-authenticate.")
                    raise DialogApiError(f"Dialog API Forbidden (403): {body}")
                if resp.status != 200:
                    body = await resp.text()
                    raise DialogApiError(f"Dialog API error ({resp.status}): {body}")

                return await resp.json()
        except aiohttp.ClientError as err:
            raise DialogApiError(f"Communication error with Dialog API: {err}") from err

    async def async_get_connections(self) -> list[dict[str, Any]]:
        """Discover all connections linked under this Dialog ID profile."""
        connections: dict[str, dict[str, Any]] = {}

        # 1. Try connections/get-list
        try:
            res_list = await self.async_post_proxy("connections/get-list", {})
            if res_list.get("success") and isinstance(res_list.get("data"), dict):
                raw_list = res_list["data"].get("connectionList", [])
                for item in raw_list:
                    conn_num = str(item.get("connection", "")).strip()
                    if conn_num:
                        connections[conn_num] = item
        except DialogAuthError:
            raise
        except Exception as err:
            _LOGGER.debug("connections/get-list check: %s", err)

        # 2. Try pay-bill/get-configs
        try:
            res_pay = await self.async_post_proxy("pay-bill/get-configs", {})
            if res_pay.get("success"):
                raw_list = res_pay.get("connectionList") or []
                for item in raw_list:
                    conn_num = str(item.get("connection", "")).strip()
                    if conn_num and conn_num not in connections:
                        connections[conn_num] = item
        except DialogAuthError:
            raise
        except Exception as err:
            _LOGGER.debug("pay-bill/get-configs check: %s", err)

        # Fallback if primary mobile was configured and no list returned
        if not connections and self._mobile_number:
            connections[self._mobile_number] = {
                "connection": self._mobile_number,
                "nickName": "Primary Mobile",
                "connectionType": "POSTPAID",
                "isPrimary": True,
            }

        # Enrich each connection with get-number-info
        enriched: list[dict[str, Any]] = []
        for conn_num, conn_data in connections.items():
            try:
                info_res = await self.async_post_proxy("pay-bill/get-number-info", {"number": conn_num})
                if info_res.get("success") and isinstance(info_res.get("data"), dict):
                    conn_data.update(info_res["data"])
            except Exception as err:
                _LOGGER.debug("Failed to enrich number info for %s: %s", conn_num, err)

            enriched.append(conn_data)

        return enriched

    async def async_get_connection_data(self, connection_number: str) -> dict[str, Any]:
        """Fetch all billing and usage metrics for a specific connection."""
        data: dict[str, Any] = {
            "connection": connection_number,
            "status": "Unknown",
            "outstanding_balance": 0.0,
            "last_bill_amount": None,
            "last_payment_amount": None,
            "payment_due_date": None,
            "last_bill_date": None,
            "last_payment_date": None,
            "data_used_gb": None,
            "data_total_gb": None,
            "data_remaining_gb": None,
        }

        # 1. Fetch number info
        try:
            info_res = await self.async_post_proxy("pay-bill/get-number-info", {"number": connection_number})
            if info_res.get("success") and isinstance(info_res.get("data"), dict):
                info = info_res["data"]
                data["status"] = info.get("connectionStatus") or ("Active" if info.get("isActive") else "Inactive")
                data["connection_type"] = info.get("connectionType", "POSTPAID")
                data["lob"] = info.get("drupalLob", "GSM")
        except Exception as err:
            _LOGGER.debug("get-number-info error for %s: %s", connection_number, err)

        # 2. Fetch current bill
        try:
            bill_res = await self.async_post_proxy("e-bill/get-current", {}, msisdn_header=connection_number)
            if bill_res.get("success") and isinstance(bill_res.get("data"), dict):
                bill_data = bill_res["data"]
                curr_bill = bill_data.get("current_bill") or {}

                def _parse_val(val: Any) -> float | None:
                    if val is None or val == "":
                        return None
                    try:
                        return float(str(val).replace(",", "").replace("LKR", "").replace("Rs", "").strip())
                    except ValueError:
                        return None

                total_payable = _parse_val(bill_data.get("total_payable") or bill_data.get("total_payable_amount"))
                if total_payable is not None:
                    data["outstanding_balance"] = total_payable

                bill_amt = _parse_val(curr_bill.get("amount") or curr_bill.get("bill_amount"))
                if bill_amt is not None:
                    data["last_bill_amount"] = bill_amt

                last_pmt = _parse_val(bill_data.get("payments"))
                if last_pmt is not None:
                    data["last_payment_amount"] = last_pmt

                data["payment_due_date"] = bill_data.get("due_date") or bill_data.get("pay_before")
                data["last_bill_date"] = curr_bill.get("bill_date") or curr_bill.get("from_date")
                data["bill_status"] = bill_data.get("bill_status")
        except Exception as err:
            _LOGGER.debug("e-bill/get-current error for %s: %s", connection_number, err)

        # 3. Fetch data usage (Broadband or Mobile)
        try:
            usage_res = await self.async_post_proxy("usage/get", {}, msisdn_header=connection_number)
            if usage_res.get("success") and isinstance(usage_res.get("data"), dict):
                u_data = usage_res["data"]
                # Parse available GB and used GB
                total = u_data.get("total_quota") or u_data.get("total")
                used = u_data.get("used_quota") or u_data.get("used")
                rem = u_data.get("remaining_quota") or u_data.get("remaining")

                def _to_gb(val: Any) -> float | None:
                    if val is None:
                        return None
                    try:
                        v = float(re.sub(r"[^\d.]", "", str(val)))
                        if "mb" in str(val).lower():
                            return round(v / 1024.0, 2)
                        return round(v, 2)
                    except ValueError:
                        return None

                data["data_total_gb"] = _to_gb(total)
                data["data_used_gb"] = _to_gb(used)
                data["data_remaining_gb"] = _to_gb(rem)
        except Exception as err:
            _LOGGER.debug("usage/get error for %s: %s", connection_number, err)

        return data
