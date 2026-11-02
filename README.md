<p align="center">
  <img src="docs/icon.png" width="128" alt="CakeUI">
</p>

<h1 align="center">CakeUI</h1>

<p align="center">
  Desktop applications written in Python, with the frontend you already know.<br>
  No Rust toolchain. No bundler required. One command to ship an app.
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#python-api">Python API</a> ·
  <a href="#javascript-api">JavaScript API</a> ·
  <a href="#building-an-app">Building</a>
</p>

---

CakeUI turns a Python process and an HTML page into a real desktop application
window. Despite the `ui` in the name it is not a component library: it is the
RPC bridge, the runtime, and the packaging toolchain that hold the two halves
together.

```python
from cakeui import App

app = App(title="Notes")

@app.command
def save_note(text: str) -> dict[str, str]:
    return {"saved": text}

app.run()
```

```js
const { saved } = await invoke("save_note", { text: "buy cake" });
```

Arguments and return values are checked with Pydantic before your code runs.
Mistakes come back to JavaScript as structured data with a `code` and a list of
offending fields, not as a string you have to parse out of a `console.log`.

## Why CakeUI

| | CakeUI | Tauri | PyTauri | raw pywebview | Electron |
|---|---|---|---|---|---|
| Backend language | Python | Rust (+ Python via PyTauri) | Python | Python | Node |
| Rust toolchain | not needed | required | required | n/a | n/a |
| Command and event layer | built in | built in | built in | hand-rolled | hand-rolled |
| Argument validation | Pydantic | serde | Pydantic | none | none |
| Frontend build step | optional | required | required | n/a | required |
| Install size | small (system webview) | small | small | small | ~150 MB |

The niche is narrow on purpose. The toolchain is pure Python, the frontend is
whatever Vite generates, and packaging is one command on top of
[Nuitka](https://nuitka.net/).

## What you get

- **A bridge, not a rewrite.** `invoke` from JavaScript, `@app.command` in
  Python. Calling across languages is one function, awaited like any other.
- **Typed end to end.** Annotations are the contract. Pydantic validates
  arguments and return values; errors arrive as `{ code, message, details }`.
- **Events in both directions.** `app.emit` / `window.emit` into `listen`, and
  `emit` into `@app.on`. Startup events fire before the window is ready and are
  buffered rather than lost.
- **Scaffolding that stays clean.** `cakeui new` runs `npm create vite` itself,
  then adds two things: a generated bridge in `src/lib/cakeui/` and one import
  line. Delete that line and you have an ordinary web app.
- **A dev server you do not manage.** `cakeui dev` starts Vite, reads the URL it
  actually bound, opens the window on it, and shuts it down when the window
  closes.
- **One-command packaging.** `cakeui build` builds the frontend, then compiles
  the whole thing with Nuitka into a `.app` bundle, a folder, or a single
  executable.
- **Icons that just work.** Ship one picture; each platform picks the format it
  needs, before and after packaging.

## Install

```bash
pip install cakeui-cli      # the CLI, plus the `cakeui` runtime it needs
# or
uv tool install cakeui-cli
```

If you only depend on the runtime and drive it from your own entry point:

```bash
pip install cakeui
```

`cakeui-cli[build]` adds Nuitka, if you want packaging installed alongside.

## Quickstart

```bash
cakeui new my-app --template vue-ts     # Vue 3 + TypeScript, scaffolded by Vite
cd my-app
cakeui dev
```

`cakeui new` installs dependencies for you when it can. If it skipped them, the
printed next steps cover it:

```bash
uv sync
(cd web && npm install)
cakeui dev
```

A window opens on the Vite dev server, with hot reload exactly as in a browser.
Edit `main.py`, edit a component, save, and both reload.

Then build:

```bash
cakeui build
```

On macOS that produces `dist/main.app`, which you can double-click. On Windows
and Linux it produces a folder or a single executable, depending on
`[tool.cakeui.build] mode`.

### What `cakeui new` writes

```
my-app/
├── pyproject.toml          the [tool.cakeui] table lives here
├── main.py                 commands and events
├── README.md
├── assets/                 the app icon: .icns, .ico, .png, and .svg source
└── web/                    produced by `npm create vite`, untouched
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── main.ts         one appended line imports ./lib/cakeui/cakeui-boot
        └── lib/cakeui/     everything CakeUI generates lives here
            ├── cakeui-boot.ts   glue: toasts, plus one handshake call at startup
            ├── cakeui.js        generated bridge
            └── cakeui.d.ts      generated types
```

Nothing of ours lands in `src/` itself. `vite.config.ts`, `index.html` and every
component are byte for byte what Vite produced, so upgrading Vite never requires
patching a template.

## A complete example

`examples/vue-notes/` is a working notes app: a JSON file, one Python module, and
one Vue component, using `invoke`, `emit` and `listen` in both directions.

```bash
cd examples/vue-notes
uv sync
npm --prefix web install
uv run cakeui dev
```

`examples/vue-notes/README.md` walks through what each file demonstrates, and it
is the shortest path to seeing how the pieces fit together.

## The icon

`assets/` holds the same picture in each format a platform wants:

| File | Used by |
|---|---|
| `assets/icon.icns` | the macOS `.app` bundle |
| `assets/icon.ico` | the Windows executable and its window |
| `assets/icon.png` | Linux, plus the window icon during `cakeui dev` |
| `assets/icon.svg` | the editable source, not shipped in the build |

To use your own artwork, overwrite the files and keep the names. `icon =
"assets/icon"` in `pyproject.toml` names a group, not a single file: on each
platform CakeUI takes the first format that exists and falls back to
`icon.png`. A lone 1024x1024 `icon.png` is enough everywhere, since Nuitka
converts it to `.icns` on macOS.

`cakeui info` prints which file the current machine would choose. `cakeui build`
copies the icon into the artifact, so the packaged app finds it at runtime.

## Python API

### `App`

```python
from cakeui import App

app = App(
    title="My App",       # defaults to the [tool.cakeui] name
    width=900,
    height=640,
    min_size=(400, 300),
    resizable=True,
    icon=None,            # defaults to [tool.cakeui] icon
    debug=False,          # or CAKEUI_DEBUG=1
    private_mode=False,   # False keeps localStorage between runs
)
```

Inside a project with a `pyproject.toml`, prefer `App.from_config()`. It reads
`[tool.cakeui]` and picks up `name`, `web`, `web_dist` and `dev_url`.

### Commands

```python
@app.command
def greet(name: str, excited: bool = False) -> dict[str, str]:
    return {"message": f"Hello, {name}!"}
```

- Parameters must be annotated; CakeUI builds a Pydantic model from the signature.
- Unknown arguments are rejected (`extra="forbid"`), so typos fail loudly.
- Return values are validated against the return annotation.
- `async def` works; coroutines are awaited for you.
- Annotations can be Pydantic models, in both directions. A `Note` argument arrives
  as a validated `Note` instance, `list[Note]` comes back as the list the frontend
  expects, and a bad payload is rejected before the body runs:

```python
from datetime import datetime

from pydantic import BaseModel

class Note(BaseModel):
    id: int
    text: str
    done: bool = False
    created_at: datetime

@app.command
def save_note(note: Note) -> list[Note]:
    ...
```

`str`, `int`, `float`, `bool`, `list[str]`, `dict`, `Literal`, `Optional` and
`datetime` / `Path` / `UUID` / `Enum` / dataclasses all work the same way: Pydantic
parses them on the way in, and the bridge serialises them on the way out. A
`ValidationError` is returned as `code: "validation_error"` with per-field details.
- Commands defined outside `main.py` use the module-level decorator:

```python
from cakeui import App, command

@command
def ping() -> str:
    return "pong"

app = App(commands=[ping])
```

### Window injection

```python
from cakeui import Window

@app.command
def notify(text: str, window: Window) -> None:
    window.emit("toast", {"text": text})   # this window only
```

`window` is supplied by CakeUI and never appears in the JavaScript call. It also
exposes `evaluate(js)`, `show()`, `hide()`, `close()` and `native` as an escape
hatch.

### Events

| Direction | Python | JavaScript |
|---|---|---|
| Python to JS | `app.emit("toast", {...})` or `window.emit(...)` | `listen("toast", fn)` |
| JS to Python | `@app.on("log")` | `emit("log", {...})` |

Events emitted before a window finishes loading are buffered and flushed on
load, so startup events are not lost.

A handler may annotate its payload with a Pydantic model and get it validated,
exactly like a command argument:

```python
class LogLine(BaseModel):
    message: str

@app.on("log")
def on_log(line: LogLine) -> None:
    print(line.message)
```

### Resources

```python
from cakeui import resource_path

logo = resource_path("assets/logo.png")
```

Resolves against the project directory during development, and against the
artifact directory once packaged (Nuitka folder, onefile and `.app` bundles, and
PyInstaller are all handled). Override with `CAKEUI_RESOURCE_ROOT` or
`set_resource_root()`.

### Errors

```python
from cakeui import CakeUIError

@app.command
def withdraw(amount: float) -> float:
    raise CakeUIError(
        "Insufficient funds",
        code="insufficient_funds",
        details={"amount": amount},
    )
```

The frontend receives `code: "insufficient_funds"` and the details object.
Unhandled exceptions become `code: "internal_error"`, with a traceback only when
`debug=True`.

## JavaScript API

There is nothing to install. The bridge is a generated file inside your project:
`cakeui new` writes `web/src/lib/cakeui/cakeui.js` and `cakeui.d.ts`, and every
`cakeui dev` refreshes them from the copy that ships inside the Python package.
The frontend and the runtime therefore cannot drift apart, and there is no
package version to keep in sync.

Upgrading CakeUI later? Run `cakeui sync` once in the project:

```bash
cakeui sync             # refresh every generated file to the installed version
cakeui sync --dry-run   # show what would change, write nothing
cakeui sync --force     # also overwrite a locally edited cakeui-boot.ts
```

It rewrites the bridge and the boot module, and re-adds the `// cakeui:bridge`
import to your entry file if it went missing. `cakeui.js` and `cakeui.d.ts` are
build output and are always overwritten; `cakeui-boot.ts` is yours to edit, so a
modified copy is left alone unless you pass `--force`.

```ts
import { invoke, listen, emit, ready, isReady, CakeUIError } from "./lib/cakeui/cakeui.js";

const user = await invoke<User>("get_user", { id: 7 });

const unlisten = listen<{ text: string }>("toast", ({ text }) => show(text));
unlisten();                                   // stop listening

await emit("log", { message: "hello" });      // reaches @app.on("log")

await ready();                                // resolve when the bridge exists
```

- `invoke` waits for `pywebviewready` on its own (10 s default), so calling it
  during page load is safe. Use `ready(ms)` for a different budget.
- Failures throw `CakeUIError`, carrying the same `code`, `message` and `details`
  the Python side produced.
- `listen("*", fn)` receives every event as `{ event, payload }`, useful for
  logging. `once`, `off` and `isReady` are there too.
- The generated files are build output. Edit `js/src/index.ts` in the repository
  instead, then run `npm --prefix js run build`.

Without a bundler, CakeUI writes a different file next to `index.html`: an IIFE
build that sets `window.cakeui` and needs no import at all.

```html
<script src="./cakeui.js"></script>
<script>
  window.cakeui.invoke("greet", { name: "Ada" }).then(console.log);
</script>
```

## Configuration

Everything the CLI needs lives in `pyproject.toml`:

```toml
[tool.cakeui]
name = "MyApp"
entry = "main.py"
web = "web"                            # source files
web_dist = "web/dist"                  # built output, preferred when present
icon = "assets/icon"                   # a stem, a directory, or one filename
dev_url = "http://localhost:5173"      # fallback if the dev server prints nothing
dev_command = "npm run dev"            # overrides package.json auto-detection

[tool.cakeui.build]                    # consumed by `cakeui build`
mode = "standalone"                    # or "onefile"
console = false
output_dir = "dist"
include_packages = ["pydantic", "pydantic_core"]
include_data_dir = ["assets=assets"]
extra_args = []
```

Paths must stay inside the project root: a `../..` typo is an error rather than
a build that reads your whole disk. Unknown keys are rejected too, so `web_src`
fails instead of silently doing nothing.

## Building an app

`cakeui build` builds the frontend, then packages it:

```bash
cakeui build                      # build web/, then compile with Nuitka
cakeui build --dry-run            # print the exact Nuitka command
cakeui build --no-web             # reuse the existing web/dist
cakeui build --mode onefile       # single executable
cakeui build --output-dir out     # somewhere other than dist/
```

Output by platform:

| Platform | `standalone` | `onefile` |
|---|---|---|
| macOS | `dist/main.app` | `dist/main.app` (pyobjc requires a bundle) |
| Windows | `dist/main.dist/` | `dist/main.exe` |
| Linux | `dist/main.dist/` | `dist/main` |

macOS needs Nuitka 4 or newer, because pyobjc only works inside an application
bundle. The frontend is copied into the artifact at its original relative path,
`pyproject.toml` ships beside it so `App.from_config()` still finds the project,
and the icon is copied in as well.

## The dev server

```bash
cakeui dev                               # run web/'s dev script, then open the window
cakeui dev --url http://localhost:5173   # window only; you run the server
cakeui dev --debug                       # inspector, plus tracebacks in errors
cakeui dev -- --some-arg                 # forwarded to main.py
```

The URL is read from the dev server's own output, because Vite prints its
address only after binding a port and may pick a different one than configured.
Closing the window terminates the server's process group, so nothing is left
listening.

The command is discovered, not assumed:

1. `[tool.cakeui] dev_command`, if set (any shell-like string, e.g. `"pnpm run dev"`);
2. otherwise a `dev` script in `<web>/package.json`, run with the package
   manager implied by the lockfile (`pnpm-lock.yaml`, `bun.lock`, `yarn.lock`,
   `package-lock.json`, else `npm`).

A project without `package.json` still loads from disk, with no dev server at
all.

## Package managers

`npm`, `pnpm`, `yarn` and `bun` all work: one table decides how to scaffold, how
to install, how to run scripts, and which lockfile marks a project as belonging
to which manager.

```bash
cakeui new my-app -p pnpm                  # explicit
pnpm dlx cakeui-cli new my-app             # detected from the invoking shell
cakeui new my-app                          # detected from a lockfile, else npm
```

Without `-p` the order is: a lockfile in the current directory, then the manager
that launched `cakeui` (that is how `pnpm dlx` and `bunx` propagate), then npm.
`cakeui dev` applies the same detection to the generated project, so a
pnpm-scaffolded app is started with `pnpm run dev` and nothing else changes.

## Templates

The frontend comes from `npm create vite`, then CakeUI merges one base layer
over it, the same split the Tauri CLI uses.

| Template | Vite template | Notes |
|---|---|---|
| `vue-ts` | `vue-ts` | default, tested end to end |
| `react-ts` | `react-ts` | |
| `svelte-ts` | `svelte-ts` | |
| `vanilla-ts` | `vanilla-ts` | plain TypeScript, no framework |

Those are only the names listed in `BUILTIN_TEMPLATES`, used for `--help` and
error hints. Any other Vite template works as well, for example `cakeui new app
--template solid-ts`. The name is passed straight to Vite, so supporting a new
framework means listing it, not writing a template.

## How it works

CakeUI owns pywebview's single `js_api` slot. Every call is one JSON envelope:

```
JS  ──invoke("greet", {name})──►  window.pywebview.api.dispatch(json)
                                  └─► validate args (Pydantic) ─► your function
JS  ◄──{ ok: true, data }──────────  json
```

Python to JavaScript events are delivered with `evaluate_js` into
`window.__cakeui._dispatch`, so they reach `listen()` handlers without the page
polling anything.

The same `js/src/index.ts` is built twice: an IIFE bundle that sets
`window.cakeui`, and an ESM bundle with `.d.ts` written into a bundler's source
tree. Both ship inside the Python package, so the runtime and the frontend can
never disagree about the protocol.

## CLI

| Command | Available in | Does |
|---|---|---|
| `cakeui new <name> [--template NAME] [-p npm\|pnpm\|yarn\|bun] [--dir PATH] [--force] [--no-install]` | v0.1 | Scaffold with Vite, then merge the base layer and the bridge |
| `cakeui dev [--url URL] [--debug] [-- extra args]` | v0.1 | Start the dev server, then the window |
| `cakeui info` | v0.1 | Print the resolved config, icon and paths |
| `cakeui sync [--dry-run] [--force]` | v0.1 | Refresh `web/src/lib/cakeui/` to the installed version |
| `cakeui build [--mode standalone\|onefile] [--output-dir PATH] [--no-web] [--dry-run]` | v0.1 | Build the frontend, then package with Nuitka |
| `cakeui typegen` | planned | Generate TypeScript declarations from Python commands |

## Limitations

Worth knowing before you commit:

- **The window is pywebview.** Native menus, tray icons, dialogs and multi-window
  behaviour are whatever pywebview provides. There is no Tauri-style native API
  surface, and CakeUI does not pretend otherwise.
- **Windows needs the WebView2 runtime.** Plan for detection or a bundled
  installer in your own release process.
- **Packaging is smoke-tested on macOS only.** `cakeui build` has been verified
  end to end there (Nuitka 4.3, `.app` bundle, app launches and finds its
  assets). Windows (`pythonnet`, WebView2) and Linux (GTK) follow the same recipe
  but have not been run; treat "launch it on a clean machine" as part of your
  release checklist.
- **No command permissions yet.** Any JavaScript in the window can call any
  registered command. Do not load untrusted remote content.
- **Anonymous types in annotations.** `get_type_hints` cannot resolve classes
  defined inside a function, so keep command argument models at module level.
- **No `py.typed` marker yet.** The runtime is fully annotated, but without
  [PEP 561](https://peps.python.org/pep-0561/) downstream `mypy` and `pyright`
  treat `cakeui` as `Any`.
- **The bridge is not on npm.** It is generated into the project, which is what
  makes `cakeui new` work offline and keeps the protocol versioned with the
  runtime. A frontend built outside a CakeUI project has to copy
  `python/src/cakeui/_bridge.mjs` in by hand for now.

## Roadmap

- `cakeui typegen`: Pydantic models into TypeScript declarations
- publish the bridge to npm, for frontends that start outside `cakeui new`
- installers, auto-update, and per-command permissions
- code signing and notarization for built apps

## Repository layout

```
python/    the `cakeui` runtime: App, commands, events, resources, config
js/        the bridge source; its builds become python/src/cakeui/_bridge.*
cli/       the `cakeui-cli` distribution: dev server, build, templates
examples/  runnable apps, `vue-notes` being the reference one
docs/      the logo, used by this README
```

Templates live inside the CLI package rather than at the repository root, so
`pip install cakeui-cli && cakeui new` works from any directory with no extra
build step or data-file juggling.

### Working on CakeUI

```bash
uv sync --all-packages      # editable installs for both distributions
npm --prefix js install
npm --prefix js run build   # regenerates js/dist and python/src/cakeui/_bridge.*
uv run pytest
npm --prefix js test
```

`python/tests/test_bridge.py` fails if a committed `_bridge.*` file drifts from
`js/dist/`, so rebuild after touching `js/src`.

Rendering a template end to end needs Node and network access for `npm create
vite`; set `CAKEUI_TEST_VITE=1` to include those tests. The rest of the CLI
suite uses a fake scaffolder and a fake dev server.

## License

Apache-2.0.
