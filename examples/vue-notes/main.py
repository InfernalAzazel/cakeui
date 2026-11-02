"""Vue Notes: the reference CakeUI example.

Four ideas, one file:

* **Annotations are the contract, and Pydantic is how you write one.** Arguments
  are validated before the body runs, so JavaScript cannot hand you an int where
  a string belongs; return values are validated too, so a command cannot quietly
  drift from what the frontend expects.
* **Models travel in both directions.** ``Note`` is the return type *and* the
  parameter type of :func:`save_note`, so the object the frontend edited is
  re-checked against the same model that produced it.
* **Writes push as well as return.** ``_write`` emits ``notes:changed``, so every
  open window follows along while the caller still gets the fresh list back.
* **``window`` is injected, never sent from JavaScript.** That is what lets a
  command answer the window that asked instead of broadcasting to all of them.

Notes live in the platform's user-data directory. CakeUI has no helper for that
yet, hence the hand-rolled path below.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

import cakeui
from cakeui import App, CakeUIError, Window
from pydantic import BaseModel, Field

MAX_TEXT = 140

if sys.platform == "darwin":
    _data_dir = Path.home() / "Library" / "Application Support"
elif os.name == "nt":
    _data_dir = Path(os.environ.get("APPDATA") or Path.home())
else:
    _data_dir = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")

STATE = _data_dir / "vue-notes" / "notes.json"

app = App.from_config()


class Note(BaseModel):
    """One shape for the file on disk, the return value and the arguments.

    ``created_at`` is a real ``datetime``: Pydantic parses the ISO string the
    frontend sends back, and the bridge serialises it to that same string on the
    way out, so neither side ever handles the conversion by hand.
    """

    id: int
    text: str
    done: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now().astimezone().replace(microsecond=0)
    )


class LogLine(BaseModel):
    """``@app.on`` handlers get the same deal: a validated model, not a raw dict."""

    message: str


def _read() -> list[Note]:
    """Notes on disk, re-validated on the way in. A corrupt file reads as empty."""
    try:
        return [Note.model_validate(item) for item in json.loads(STATE.read_text("utf-8"))]
    except (OSError, ValueError):
        return []


def _write(notes: list[Note]) -> list[Note]:
    """Persist and broadcast in one step, so no command can forget half of it."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = [note.model_dump(mode="json") for note in notes]
    STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    app.emit("notes:changed", {"count": len(notes)})
    return notes


def _find(notes: list[Note], note_id: int) -> Note:
    """The note with this id; anything else is a domain error, not a no-op."""
    for note in notes:
        if note.id == note_id:
            return note
    raise CakeUIError(
        f"No note with id {note_id}; it was probably deleted already.",
        code="note_not_found",
        details={"note_id": note_id},
    )


@app.command
def list_notes() -> list[Note]:
    """Newest first, the order the file is kept in. The return annotation means
    the bridge validates the list before it leaves Python."""
    return _read()


@app.command
def add_note(text: str) -> list[Note]:
    """A plain builtin argument: ``invoke("add_note", { text })`` is all it takes."""
    cleaned = text.strip()
    if not 1 <= len(cleaned) <= MAX_TEXT:
        raise CakeUIError(
            f"Notes must be 1-{MAX_TEXT} characters, got {len(cleaned)}.",
            code="invalid_note",
            details={"field": "text", "min": 1, "max": MAX_TEXT, "actual": len(cleaned)},
        )

    notes = _read()
    notes.insert(0, Note(id=max((note.id for note in notes), default=0) + 1, text=cleaned))
    return _write(notes)


@app.command
def save_note(note: Note) -> list[Note]:
    """A model argument: the frontend sends the note it just edited and Pydantic
    rebuilds it. Editing happens here, not in the UI, so the checkbox is a real
    round trip rather than local state that could disagree with the file."""
    notes = _read()
    index = next((i for i, existing in enumerate(notes) if existing.id == note.id), None)
    if index is None:
        raise CakeUIError(
            f"No note with id {note.id}; it was probably deleted already.",
            code="note_not_found",
            details={"note_id": note.id},
        )

    notes[index] = note
    return _write(notes)


@app.command
def delete_note(note_id: int, window: Window) -> list[Note]:
    """``window`` is injected by CakeUI; it never appears in the call arguments."""
    notes = _read()
    notes.remove(_find(notes, note_id))  # a missing id raises before anything is written
    _write(notes)
    # app.emit reached every window; window.emit reaches only the caller, which is
    # why only the window you clicked in shows the toast.
    window.emit("toast", {"text": f"Deleted note #{note_id}"})
    return notes


@app.command
def clear_done() -> list[Note]:
    """Drop every finished note and return the survivors."""
    return _write([note for note in _read() if not note.done])


@app.command
def app_info() -> dict:
    """Facts for the footer. ``max_text`` lives here because Python is the one
    that enforces it; the frontend only mirrors it for the counter."""
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "cakeui": cakeui.__version__,
        "notes_file": str(STATE),
        "max_text": MAX_TEXT,
    }


@app.command
def notify(text: str, window: Window) -> None:
    """``cakeui-boot.ts`` calls this once at startup to prove the round trip."""
    window.emit("toast", {"text": text})


@app.command
def crash(kind: str = "boom") -> None:
    """Fail on purpose: the frontend sees ``code == "internal_error"``, and the
    traceback stays server-side unless the app runs with ``debug=True``."""
    raise RuntimeError(f"deliberate {kind} from Python")


@app.on("log")
def on_log(line: LogLine) -> None:
    """Frontend ``emit("log", ...)`` lands in the terminal running the app."""
    print(f"[frontend] {line.message}")


if __name__ == "__main__":
    app.run()
