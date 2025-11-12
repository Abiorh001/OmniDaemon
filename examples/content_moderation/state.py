import json
import os
from pathlib import Path
from typing import Dict

STATE_DIR = Path.home() / ".omnicoreagent"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_TRACKER = STATE_DIR / "moderation_state.json"
INGEST_ROOT = Path(
    os.getenv("CONTENT_MODERATION_INGEST_ROOT", STATE_DIR / "moderation_ingest")
)
INGEST_ROOT.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict[str, Dict[str, Dict[str, str]]]:
    if STATE_TRACKER.exists():
        try:
            return json.loads(STATE_TRACKER.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: Dict[str, Dict[str, Dict[str, str]]]) -> None:
    STATE_TRACKER.write_text(json.dumps(state, indent=2))


def load_directory_snapshot(directory: Path) -> Dict[str, Dict[str, str]]:
    state = load_state()
    return state.get(str(directory), {})


def save_directory_snapshot(
    directory: Path, snapshot: Dict[str, Dict[str, str]]
) -> None:
    state = load_state()
    state[str(directory)] = snapshot
    save_state(state)


__all__ = [
    "STATE_DIR",
    "STATE_TRACKER",
    "INGEST_ROOT",
    "load_state",
    "save_state",
    "load_directory_snapshot",
    "save_directory_snapshot",
]
