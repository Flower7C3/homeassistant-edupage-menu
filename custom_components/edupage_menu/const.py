from datetime import timedelta

DOMAIN = "edupage_menu"
DEFAULT_URL = "https://edupage.example.com/menu/"
DEFAULT_NAME = "Jadłospis"
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)

CONF_URL = "url"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_WEEKS_BACK = "weeks_back"
CONF_WEEKS_AHEAD = "weeks_ahead"
CONF_WEEKS_RANGE = "weeks_range"
CONF_TITLE_SHOW_WEEKDAY = "title_show_weekday"
CONF_MENU_TODAY_FALLBACK = "menu_today_fallback"

DEFAULT_WEEKS_BACK = 1
DEFAULT_WEEKS_AHEAD = 4
DEFAULT_WEEKS_RANGE = "1-4"
DEFAULT_TITLE_SHOW_WEEKDAY = True
DEFAULT_MENU_TODAY_FALLBACK = False

REQUEST_HEADERS = {
    "User-Agent": "HomeAssistant/edupage_menu",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pl,en;q=0.8",
}

URL_BASE = "/edupage_menu"
JS_CARD_FILENAME = "edupage-menu-day.js"
JS_CARD_VERSION = "21"