"""Stored calls and human labels."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALLS_DIR = ROOT / "data/calls"
LABELS = ROOT / "data/labels/human.jsonl"


def load_calls(directory: Path = CALLS_DIR) -> dict[str, dict]:
    calls = {}
    for path in sorted(directory.glob("*/*.json")):
        data = json.loads(path.read_text())
        call = data.get("call", data)
        calls[call["call_id"]] = call
    return calls


def load_human_labels(path: Path = LABELS) -> dict[str, dict[str, int]]:
    """Latest label per call_id wins, so re-labelling a call overwrites the old scores."""
    labels: dict[str, dict[str, int]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                labels[row["call_id"]] = {k: int(v) for k, v in row["scores"].items()}
    return labels


def save_human_label(call_id: str, scores: dict[str, int], labeller: str, notes: str = "",
                     path: Path = LABELS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"call_id": call_id, "scores": scores, "labeller": labeller, "notes": notes,
           "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
