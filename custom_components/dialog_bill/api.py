"""API Client for Dialog Axiata (MyDialog & Dialog ID)."""

from __future__ import annotations

from http.cookies import SimpleCookie
import logging
import re
from typing import Any
import urllib.parse

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0"


class DialogAuthError(Exception):
    """Exception raised when authentication fails."""


class DialogApiError(Exception):
    """Exception raised when API calls fail."""


def _parse_amount(val: Any) -> float | None:
    """Parse a currency string like 'Rs. 290.82' or '3,000.00' into a float."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return round(float(val), 2)
    cleaned = re.sub(r"[^\d.-]", "", str(val).replace(",", ""))
    # Strip leading dots if any (e.g. from 'Rs. 290.82')
    cleaned = cleaned.lstrip(".")
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _parse_data_to_gb(val: Any) -> float | None:
    """Parse a data string like '4.26 GB' or '10 MB' into gigabytes."""
    if val is None or val == "":
        return None
    val_str = str(val).strip().upper()
    match = re.search(r"([\d.]+)\s*(TB|GB|MB|KB)?", val_str)
    if not match:
        return None
    try:
        num = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2) or "GB"
    if unit == "TB":
        return round(num * 1024.0, 2)
    if unit == "MB":
        return round(num / 1024.0, 3)
    if unit == "KB":
        return round(num / (1024.0 * 1024.0), 4)
    return round(num, 2)


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

        # Seed aiohttp cookie jar with stored cookies so redirects work seamlessly
        if self._cookies and hasattr(self._session, "cookie_jar"):
            try:
                self._session.cookie_jar.update_cookies(
                    self._cookies, URL("https://dialog.lk/")
                )
                did_keys = {"commonAuthId", "opbs", "JSESSIONID"}
                did_cookies = {
                    k: v
                    for k, v in self._cookies.items()
                    if k in did_keys or "incap" in k
                }
                if did_cookies:
                    self._session.cookie_jar.update_cookies(
                        did_cookies, URL("https://did.dialog.lk/")
                    )
            except Exception as err:
                _LOGGER.debug("Could not seed cookie jar: %s", err)

    @property
    def cookies(self) -> dict[str, str]:
        """Return the current session cookies."""
        return self._cookies

    def _extract_from_single_response(self, resp: aiohttp.ClientResponse) -> None:
        """Extract cookies from a single ClientResponse and its raw Set-Cookie headers."""
        for cookie in resp.cookies.values():
            old_val = self._cookies.get(cookie.key)
            if old_val != cookie.value:
                self._cookies[cookie.key] = cookie.value
                self.cookies_updated = True

        for raw_header in resp.headers.getall("Set-Cookie", []):
            sc = SimpleCookie()
            try:
                sc.load(raw_header)
                for key, morsel in sc.items():
                    old_val = self._cookies.get(key)
                    if old_val != morsel.value:
                        self._cookies[key] = morsel.value
                        self.cookies_updated = True
            except Exception:
                pass

    def _extract_cookies(self, response: aiohttp.ClientResponse) -> None:
        """Extract and store cookies from redirect history, final response, and session jar."""
        if response.history:
            for hist_resp in response.history:
                self._extract_from_single_response(hist_resp)

        self._extract_from_single_response(response)

        if hasattr(self._session, "cookie_jar"):
            # Check did.dialog.lk first, and dialog.lk second so that dialog.lk's
            # portal cookies (self_token, SSESS) take final precedence.
            for domain_url in (URL("https://did.dialog.lk/"), URL("https://dialog.lk/")):
                try:
                    for cookie in self._session.cookie_jar.filter_cookies(domain_url).values():
                        old_val = self._cookies.get(cookie.key)
                        if old_val != cookie.value:
                            self._cookies[cookie.key] = cookie.value
                            self.cookies_updated = True
                except Exception:
                    pass

    async def async_start_login(self, mobile_number: str) -> dict[str, Any]:
        """Initiate Dialog ID SSO login and request SMS OTP.

        Returns a dictionary with 'session_data_key' and initial cookies.
        """
        clean_number = mobile_number.strip().replace(" ", "").replace("-", "")
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
            query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
            if "sessionDataKey" in query:
                session_data_key = query["sessionDataKey"][0]
            else:
                raise DialogAuthError("Could not retrieve sessionDataKey from Dialog ID login page")
        else:
            session_data_key = match.group(1)

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

        if "otp" not in otp_page_html.lower() and "otp" not in otp_final_url.lower():
            if "invalid" in otp_page_html.lower():
                raise DialogAuthError("Invalid mobile number format for Dialog ID")
            raise DialogAuthError("Dialog ID did not return an OTP prompt page")

        sdk_match = re.search(
            r'name=["\']sessionDataKey["\']\s+id=["\']sessionDataKey["\']\s+value=["\']([^"\']+)["\']',
            otp_page_html,
        )
        if sdk_match:
            session_data_key = sdk_match.group(1)

        return {
            "session_data_key": session_data_key,
            "cookies": dict(self._cookies),
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

        if "invalid otp" in final_html.lower() or "incorrect" in final_html.lower():
            raise DialogAuthError("The OTP entered is incorrect or expired")

        has_auth = (
            "self_token" in self._cookies
            or any(k.startswith("SSESS") for k in self._cookies)
        )
        if not has_auth and "dialog.lk" not in final_url:
            raise DialogAuthError("Authentication succeeded but failed to acquire Dialog web session cookie")

        _LOGGER.debug("Dialog authentication successful, acquired session cookies")
        return dict(self._cookies)

    async def async_refresh_sso_session(self) -> bool:
        """Silently refresh Dialog session tokens via did.dialog.lk SSO without requiring an OTP."""
        _LOGGER.debug("Attempting silent Dialog SSO token refresh...")
        sso_url = "https://dialog.lk/sso-login?language=en&destination=L215ZGlhbG9nLXdlYj9sYW5ndWFnZT1lbg=="
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            if hasattr(self._session, "cookie_jar"):
                self._session.cookie_jar.update_cookies(self._cookies, URL("https://dialog.lk/"))
                did_keys = {"commonAuthId", "opbs", "JSESSIONID"}
                did_cookies = {
                    k: v
                    for k, v in self._cookies.items()
                    if k in did_keys or "incap" in k
                }
                if did_cookies:
                    self._session.cookie_jar.update_cookies(did_cookies, URL("https://did.dialog.lk/"))

            async with self._session.get(
                sso_url, headers=headers, allow_redirects=True
            ) as resp:
                self._extract_cookies(resp)
                final_url = str(resp.url)
                if "mydialog-web" in final_url and (
                    "self_token" in self._cookies
                    or any(k.startswith("SSESS") for k in self._cookies)
                ):
                    _LOGGER.info("Successfully refreshed Dialog SSO session token silently")
                    return True
                _LOGGER.debug("SSO refresh ended at non-target URL: %s", final_url)
        except Exception as err:
            _LOGGER.debug("Silent Dialog SSO token refresh failed: %s", err)

        return False

    async def async_post_proxy(
        self,
        route: str,
        payload: dict[str, Any] | None = None,
        msisdn_header: str | None = None,
        is_retry: bool = False,
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
            cookies_kwarg = None if hasattr(self._session, "cookie_jar") else self._cookies
            async with self._session.post(
                url,
                json=data,
                headers=headers,
                cookies=cookies_kwarg,
            ) as resp:
                self._extract_cookies(resp)
                if resp.status == 403:
                    body = await resp.text()
                    is_auth_error = (
                        "Token not found" in body
                        or "Session not found" in body
                        or "Forbidden" in body
                    )
                    if is_auth_error and not is_retry:
                        _LOGGER.info(
                            "Dialog API session token expired; attempting silent SSO session renewal"
                        )
                        if await self.async_refresh_sso_session():
                            return await self.async_post_proxy(
                                route, payload, msisdn_header, is_retry=True
                            )
                        raise DialogAuthError(
                            "Session expired and silent renewal failed. Please re-authenticate."
                        )
                    if is_auth_error:
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

        if not connections and self._mobile_number:
            connections[self._mobile_number] = {
                "connection": self._mobile_number,
                "nickName": "Primary Mobile",
                "connectionType": "POSTPAID",
                "isPrimary": True,
            }

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
        """Fetch all billing, prepaid balance, and usage metrics for a specific connection."""
        data: dict[str, Any] = {
            "connection": connection_number,
            "connection_type": "POSTPAID",
            "lob": "GSM",
            "status": "Unknown",
            "package": None,
            # Postpaid metrics
            "outstanding_balance": None,
            "current_usage": None,
            "last_bill_amount": None,
            "last_payment_amount": None,
            "payment_due_date": None,
            "last_bill_date": None,
            "last_payment_date": None,
            # Prepaid metrics
            "prepaid_balance": None,
            "balance_expiry_date": None,
            # Data quota metrics
            "data_remaining_gb": None,
        }

        # 1. Fetch number info
        try:
            info_res = await self.async_post_proxy("pay-bill/get-number-info", {"number": connection_number})
            if info_res.get("success") and isinstance(info_res.get("data"), dict):
                info = info_res["data"]
                data["status"] = info.get("connectionStatus") or ("Active" if info.get("isActive") else "Inactive")
                data["connection_type"] = str(info.get("connectionType") or "POSTPAID").upper()
                data["lob"] = info.get("drupalLob") or info.get("lob") or "GSM"
        except Exception as err:
            _LOGGER.debug("get-number-info error for %s: %s", connection_number, err)

        # 2. Fetch dashboard navigation sections (for balance_summery_section & my_packages_section)
        section_terms: dict[str, str] = {}
        try:
            nav_res = await self.async_post_proxy(
                "dash/get-nav-config", {"nav_id": "492"}, msisdn_header=connection_number
            )
            if nav_res.get("success") and isinstance(nav_res.get("data"), dict):
                for sec in nav_res["data"].get("sections") or []:
                    sec_id = sec.get("id")
                    term_id = sec.get("term_id")
                    if sec_id:
                        section_terms[sec_id] = str(term_id) if term_id is not None else "412"
        except Exception as err:
            _LOGGER.debug("dash/get-nav-config error for %s: %s", connection_number, err)

        # 3. Fetch balance_summery_section (Prepaid Balance, Validity, and Data Remaining)
        bal_term_id = section_terms.get(
            "balance_summery_section",
            "412" if data["connection_type"] == "PREPAID" else "443",
        )
        try:
            bal_res = await self.async_post_proxy(
                "dash/get-component-data",
                {"nav_id": "492", "id": "balance_summery_section", "term_id": bal_term_id},
                msisdn_header=connection_number,
            )
            if bal_res.get("success") and isinstance(bal_res.get("data"), dict):
                tab_contents = bal_res["data"].get("tabContents") or []
                for tab in tab_contents:
                    tab_id = tab.get("id")
                    cards = tab.get("cardData") or []
                    if tab_id == "money" and cards:
                        first_card = cards[0]
                        amt = _parse_amount(first_card.get("middleLabel"))
                        if amt is not None:
                            data["prepaid_balance"] = amt
                        bottom = str(first_card.get("bottomLabel") or "")
                        if "valid till" in bottom.lower():
                            exp_str = re.sub(r"(?i)valid\s+till\s*", "", bottom).strip()
                            data["balance_expiry_date"] = exp_str
                    elif tab_id == "data" and cards:
                        total_rem_gb = 0.0
                        found_data = False
                        for card in cards:
                            rem = _parse_data_to_gb(card.get("middleLabel"))
                            if rem is not None:
                                total_rem_gb += rem
                                found_data = True
                        if found_data:
                            data["data_remaining_gb"] = round(total_rem_gb, 2)
        except Exception as err:
            _LOGGER.debug("balance_summery_section error for %s: %s", connection_number, err)

        # 4. Fetch my_packages_section (Tariff / Plan Name)
        pkg_term_id = section_terms.get(
            "my_packages_section",
            "465" if data["connection_type"] == "PREPAID" else "471",
        )
        try:
            pkg_res = await self.async_post_proxy(
                "dash/get-component-data",
                {"nav_id": "492", "id": "my_packages_section", "term_id": pkg_term_id},
                msisdn_header=connection_number,
            )
            if pkg_res.get("success") and isinstance(pkg_res.get("data"), dict):
                pkgs = pkg_res["data"].get("packages") or []
                if pkgs and isinstance(pkgs[0], dict):
                    pkg_name = pkgs[0].get("package_name")
                    if pkg_name:
                        data["package"] = str(pkg_name).strip()
        except Exception as err:
            _LOGGER.debug("my_packages_section error for %s: %s", connection_number, err)

        # 5. Connection-type specific endpoints
        if data["connection_type"] == "PREPAID":
            # Fallback to addon/get-balance if prepaid_balance wasn't found in balance_summery_section
            if data["prepaid_balance"] is None:
                try:
                    addon_bal = await self.async_post_proxy(
                        "addon/get-balance", {}, msisdn_header=connection_number
                    )
                    if addon_bal.get("success"):
                        amt = _parse_amount(addon_bal.get("data"))
                        if amt is not None:
                            data["prepaid_balance"] = amt
                except Exception as err:
                    _LOGGER.debug("addon/get-balance error for %s: %s", connection_number, err)
        else:
            # Postpaid: Fetch current bill & payment history
            try:
                bill_res = await self.async_post_proxy(
                    "e-bill/get-current", {}, msisdn_header=connection_number
                )
                if bill_res.get("success") and isinstance(bill_res.get("data"), dict):
                    bill_data = bill_res["data"]
                    curr_bill = bill_data.get("current_bill") or {}
                    prev_bill = bill_data.get("previous_bill") or {}

                    total_payable = _parse_amount(
                        bill_data.get("total_payable") or bill_data.get("total_payable_amount")
                    )
                    if total_payable is not None:
                        data["outstanding_balance"] = total_payable

                    curr_usage = _parse_amount(curr_bill.get("amount") or curr_bill.get("bill_amount"))
                    if curr_usage is not None:
                        data["current_usage"] = curr_usage

                    prev_amt = _parse_amount(prev_bill.get("amount"))
                    if prev_amt is not None:
                        data["last_bill_amount"] = prev_amt
                    elif curr_usage is not None:
                        data["last_bill_amount"] = curr_usage

                    last_pmt = _parse_amount(bill_data.get("payments"))
                    if last_pmt is not None:
                        data["last_payment_amount"] = last_pmt

                    data["payment_due_date"] = bill_data.get("pay_before") or bill_data.get("due_date")
                    data["last_bill_date"] = (
                        curr_bill.get("from_date")
                        or curr_bill.get("bill_date")
                        or bill_data.get("due_date")
                    )
                    data["bill_status"] = bill_data.get("bill_status")
            except Exception as err:
                _LOGGER.debug("e-bill/get-current error for %s: %s", connection_number, err)

            try:
                pmt_res = await self.async_post_proxy(
                    "payment-history/read", {}, msisdn_header=connection_number
                )
                if pmt_res.get("success") and isinstance(pmt_res.get("data"), list) and pmt_res["data"]:
                    latest_pmt = pmt_res["data"][0]
                    if isinstance(latest_pmt, dict):
                        data["last_payment_date"] = latest_pmt.get("date")
                        if data["last_payment_amount"] is None:
                            data["last_payment_amount"] = _parse_amount(latest_pmt.get("amount"))
            except Exception as err:
                _LOGGER.debug("payment-history/read error for %s: %s", connection_number, err)

        return data
