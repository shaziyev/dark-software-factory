from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring
from keyring.errors import KeyringError

SERVICE_NAME = "Talk2Excel"
KEY_NAME = "openai_api_key"
CONFIG_DIR = Path.home() / ".talk2excel"
SETTINGS_PATH = CONFIG_DIR / "settings.json"


@dataclass(slots=True)
class AppSettings:
    model: str = "gpt-5.4"
    show_raw_output: bool = False
    store_api_key: bool = True


def load_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()

    return AppSettings(
        model=str(data.get("model", "gpt-5.4")),
        show_raw_output=bool(data.get("show_raw_output", False)),
        store_api_key=bool(data.get("store_api_key", False)),
    )


def save_settings(settings: AppSettings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def load_api_key() -> str:
    try:
        return keyring.get_password(SERVICE_NAME, KEY_NAME) or ""
    except KeyringError:
        return ""


def save_api_key(api_key: str) -> None:
    if not api_key:
        return

    keyring.set_password(SERVICE_NAME, KEY_NAME, api_key)


def delete_api_key() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, KEY_NAME)
    except KeyringError:
        return
