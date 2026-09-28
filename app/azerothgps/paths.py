"""Where things live."""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESOURCES = REPO  # overrides/, addon/
ADDON_DIR = REPO / "addon" / "AzerothGPS"


def data_dir() -> Path:
    """Writable, git-ignored data: extracted client data, debug output. AZEROTHGPS_DATA overrides."""
    env = os.environ.get("AZEROTHGPS_DATA")
    return Path(env) if env else REPO / "data"


DEFAULT_WOW = Path(r"C:\Program Files (x86)\World of Warcraft")
DEFAULT_FLAVOR = "_classic_beta_"  # WoW: Forever


def wtf_account_dir(wow_path: Path = DEFAULT_WOW, flavor: str = DEFAULT_FLAVOR) -> Path:
    return Path(wow_path) / flavor / "WTF" / "Account"
