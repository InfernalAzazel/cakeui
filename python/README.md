<p align="center">
  <img src="https://raw.githubusercontent.com/InfernalAzazel/cakeui/main/docs/icon.png" width="120" alt="CakeUI">
</p>

<h1 align="center">cakeui</h1>

<p align="center">
  Desktop apps with Python and a web frontend, no Rust or bundler required.
</p>

This is the runtime package. It wraps [pywebview](https://pywebview.flowrl.com/),
validates arguments with Pydantic, and ships the JavaScript bridge your frontend
imports. For scaffolding, the dev server and Nuitka packaging, install
[`cakeui-cli`](https://pypi.org/project/cakeui-cli/) instead.

## Install

```bash
pip install cakeui          # runtime only
pip install cakeui-cli      # the `cakeui` command, which needs this runtime
```

## Hello world

```python
from cakeui import App

app = App(title="Notes")


@app.command
def save_note(text: str) -> dict[str, str]:
    return {"saved": text}


if __name__ == "__main__":
    app.run()
```

```js
const { saved } = await cakeui.invoke("save_note", { text: "buy cake" });
```

`save_note` is checked against its annotations before the body runs, so a bad
call from JavaScript is rejected with structured data instead of a string in
`console.log`.

## What is in the box

| | |
|---|---|
| `App`, `@app.command`, `@app.on` | the command and event layer |
| Pydantic validation | arguments and return values, with structured errors |
| `Window` injection | `window.emit`, `evaluate`, `show`, `hide`, `close` |
| `resource_path` | find bundled files in dev and after packaging |
| window icon | picked per platform from `[tool.cakeui] icon` |
| `_bridge.js` / `_bridge.mjs` | the prebuilt frontend bridge, copied into your project |

The bridge files are generated from the `js/` directory in the repository, so
the runtime and the npm package cannot drift apart.

## Documentation

Full documentation, the CLI reference and the packaging guide live in the
[repository](https://github.com/InfernalAzazel/cakeui).

## License

Apache-2.0.
