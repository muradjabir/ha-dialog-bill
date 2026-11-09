"""Constants for the Dialog Bill integration."""

DOMAIN = "dialog_bill"

CONF_MOBILE_NUMBER = "mobile_number"
CONF_SESSION_COOKIES = "cookies"
CONF_SESSION_DATA_KEY = "session_data_key"
CONF_SELECTED_CONNECTIONS = "selected_connections"
CONF_AUTH_METHOD = "auth_method"
CONF_SCAN_INTERVAL = "scan_interval"

AUTH_METHOD_OTP = "otp"
AUTH_METHOD_COOKIE = "cookie"

DEFAULT_SCAN_INTERVAL = 7200  # 2 hours in seconds
MIN_SCAN_INTERVAL = 3600      # 1 hour minimum to avoid aggressive polling
