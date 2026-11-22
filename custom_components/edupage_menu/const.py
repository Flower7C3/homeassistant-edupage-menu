from datetime import timedelta

DOMAIN = "edupage_menu"
DEFAULT_URL = "https://edupage.example.com/menu/"
DEFAULT_NAME = "Jadłospis"
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)

CONF_URL = "url"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"

REQUEST_HEADERS = {
    "User-Agent": "HomeAssistant/edupage_menu",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pl,en;q=0.8",
}

URL_BASE = "/edupage_menu"
JS_CARD_FILENAME = "edupage-menu-day.js"
JS_CARD_VERSION = "6"