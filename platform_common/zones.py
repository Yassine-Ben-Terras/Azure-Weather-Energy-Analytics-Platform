"""Shared energy areas and their representative weather points."""
import json
from pathlib import Path

ZONES = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
