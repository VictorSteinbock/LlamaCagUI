"""Typed persistence over QSettings.

One place owns every user-visible setting: the cag-api base URL, the optional
stack directory, chat defaults, and the welcome-dialog flag. Everything is a
typed property with a sane default, so the rest of the app never touches
QSettings directly or worries about string round-tripping.
"""

from pathlib import Path

from PySide6.QtCore import QSettings

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2

# Sibling repos are named llama-cag-n8n / llama-cag-n8N; match the family.
STACK_DIR_GLOB = "llama-cag-n8*"
COMPOSE_FILENAME = "docker-compose.yml"


def _to_bool(value: object, default: bool) -> bool:
    # QSettings on some backends hands booleans back as the strings "true"/
    # "false"; normalise both those and native bools.
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def detect_stack_dir(search_root: Path | None = None) -> Path | None:
    """Return the first sibling directory that looks like the stack, or None.

    A directory qualifies if its name matches ``llama-cag-n8*`` and it contains
    a ``docker-compose.yml``. ``search_root`` defaults to the parent of this
    installed package's repository (i.e. the folder holding sibling checkouts).
    """
    if search_root is None:
        # llamacag_ui/config.py -> repo root -> parent holding sibling repos.
        search_root = Path(__file__).resolve().parent.parent.parent
    try:
        candidates = sorted(search_root.glob(STACK_DIR_GLOB))
    except OSError:
        return None
    for candidate in candidates:
        if candidate.is_dir() and (candidate / COMPOSE_FILENAME).is_file():
            return candidate
    return None


class AppConfig:
    """Typed façade over ``QSettings("LlamaCag", "LlamaCagUI")``."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings("LlamaCag", "LlamaCagUI")

    # --- cag-api -----------------------------------------------------------

    @property
    def api_url(self) -> str:
        return str(self._settings.value("api_url", DEFAULT_API_URL))

    @api_url.setter
    def api_url(self, value: str) -> None:
        self._settings.setValue("api_url", value.strip() or DEFAULT_API_URL)

    # --- stack directory ---------------------------------------------------

    @property
    def stack_dir(self) -> Path | None:
        raw = self._settings.value("stack_dir", "")
        text = str(raw).strip()
        return Path(text) if text else None

    @stack_dir.setter
    def stack_dir(self, value: Path | str | None) -> None:
        self._settings.setValue("stack_dir", str(value) if value else "")

    # --- chat defaults -----------------------------------------------------

    @property
    def max_tokens(self) -> int:
        try:
            return int(self._settings.value("chat/max_tokens", DEFAULT_MAX_TOKENS))
        except (TypeError, ValueError):
            return DEFAULT_MAX_TOKENS

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        self._settings.setValue("chat/max_tokens", int(value))

    @property
    def temperature(self) -> float:
        try:
            return float(self._settings.value("chat/temperature", DEFAULT_TEMPERATURE))
        except (TypeError, ValueError):
            return DEFAULT_TEMPERATURE

    @temperature.setter
    def temperature(self, value: float) -> None:
        self._settings.setValue("chat/temperature", float(value))

    # --- welcome flag ------------------------------------------------------

    @property
    def show_welcome(self) -> bool:
        return _to_bool(self._settings.value("ui/show_welcome", True), True)

    @show_welcome.setter
    def show_welcome(self, value: bool) -> None:
        self._settings.setValue("ui/show_welcome", bool(value))

    # --- helpers -----------------------------------------------------------

    def autodetect_stack_dir(self) -> Path | None:
        """Detect and persist the stack directory; return what was found."""
        found = detect_stack_dir()
        if found is not None:
            self.stack_dir = found
        return found

    def sync(self) -> None:
        self._settings.sync()
