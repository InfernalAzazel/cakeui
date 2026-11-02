# cakeui-cli

The `cakeui` command: scaffold a desktop app, run it against a live dev server,
and package it with [Nuitka](https://nuitka.net/).

It depends on the [`cakeui`](https://pypi.org/project/cakeui/) runtime, so
installing this gives you both.

## Install

```bash
pip install cakeui-cli
# or, isolated from your project's environment:
uv tool install cakeui-cli
```

Packaging needs Nuitka, which is an optional extra so that `cakeui new` and
`cakeui dev` stay cheap:

```bash
pip install "cakeui-cli[build]"
```

## Commands

| Command | Does |
|---|---|
| `cakeui new <name> [--template NAME] [-p npm\|pnpm\|yarn\|bun] [--dir PATH] [--force] [--no-install]` | Scaffold with `npm create vite`, then merge the CakeUI layer |
| `cakeui dev [--url URL] [--debug] [-- extra args]` | Start the frontend dev server, then open the window |
| `cakeui info` | Print the resolved config and web paths |
| `cakeui build [--mode standalone\|onefile] [--output-dir PATH] [--no-web] [--dry-run]` | Build the frontend, then package with Nuitka |

`cakeui new` supports `vue-ts`, `react-ts`, `svelte-ts` and `vanilla-ts` by name,
but any Vite template works, because the name is passed straight to Vite.

## Quickstart

```bash
cakeui new my-app --template vue-ts
cd my-app
(cd web && npm install)
cakeui dev
```

`cakeui build` produces a `.app` on macOS (pyobjc only works inside one) and a
`main.dist/` folder or a single executable on Windows and Linux, depending on
`mode` in `[tool.cakeui.build]`.

Settings live in the generated `pyproject.toml`:

```toml
[tool.cakeui]
name = "MyApp"
entry = "main.py"
web = "web"
web_dist = "web/dist"

[tool.cakeui.build]
mode = "standalone"      # or "onefile"
console = false
output_dir = "dist"
```

## Documentation

Full documentation lives in the [repository](https://github.com/InfernalAzazel/cakeui).

## License

Apache-2.0.
