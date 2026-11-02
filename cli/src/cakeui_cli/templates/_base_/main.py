"""{{display_name}}: a CakeUI desktop app.

`cakeui dev` starts the frontend dev server, waits for it to report a URL, and
opens the window on that URL. Closing the window shuts the dev server down.
"""

from __future__ import annotations

from cakeui import App, Window

app = App.from_config()


@app.command
def greet(name: str, excited: bool = False) -> dict[str, str]:
    """Annotations are the validation contract; Pydantic checks them first."""
    message = f"Hello, {name}!"
    return {"message": message.upper() if excited else message}


@app.command
def notify(text: str, window: Window) -> None:
    """`window` is injected by CakeUI and never comes from JavaScript."""
    window.emit("toast", {"text": text})


@app.on("log")
def on_log(payload: dict) -> None:
    print(f"[frontend] {payload.get('message', '')}")


if __name__ == "__main__":
    app.run()
