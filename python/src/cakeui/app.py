"""应用对象：窗口、命令、事件，以及 pywebview 的启动。"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ._json import dumps, js_string
from .bridge import ensure_bridge_file
from .commands import CommandSpec
from .config import CakeUIConfig, load_config
from .errors import CakeUIError, ConfigError
from .resources import resource_root
from .router import Router, fail
from .window import Window

DEV_URL_ENV = "CAKEUI_DEV_URL"
DEBUG_ENV = "CAKEUI_DEBUG"

# 够覆盖一次启动时的事件突发，又不至于让一个永不加载的窗口把内存吃光。
_MAX_PENDING_EVENTS = 200


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


class _JsApi:
    """唯一暴露给 JavaScript 的对象。

    所有属性都以下划线开头：pywebview 会把 ``js_api`` 上的公开成员镜像到
    ``window.pywebview.api``，而我们只想在那里露出 ``dispatch`` 一个方法。
    """

    def __init__(self, app: App) -> None:
        self._app = app
        self._window: Window | None = None

    def _bind(self, window: Window) -> None:
        self._window = window

    def dispatch(self, payload: str) -> str:
        """唯一的 RPC 入口，返回 JSON 信封，从不抛异常。"""
        try:
            return self._app.router.handle(payload, self._window)
        except Exception as exc:  # 兜底：这里已经跨进 pywebview 的线程
            return fail(CakeUIError(f"{type(exc).__name__}: {exc}", code="internal_error"))


class App:
    """一个 CakeUI 应用。

    最简用法::

        app = App(title="Notes")

        @app.command
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        if __name__ == "__main__":
            app.run()
    """

    def __init__(
        self,
        *,
        title: str | None = None,
        width: int = 900,
        height: int = 640,
        min_size: tuple[int, int] = (400, 300),
        resizable: bool = True,
        background_color: str = "#ffffff",
        url: str | None = None,
        web: str | os.PathLike[str] | None = None,
        debug: bool | None = None,
        gui: str | None = None,
        private_mode: bool = False,
        storage_path: str | os.PathLike[str] | None = None,
        config: CakeUIConfig | None = None,
        commands: Iterable[Callable[..., Any]] = (),
    ) -> None:
        self.title = title or (config.name if config else "CakeUI")
        self.width = width
        self.height = height
        self.min_size = min_size
        self.resizable = resizable
        self.background_color = background_color
        self.url = url
        self.gui = gui
        self.config = config
        self.debug = _env_flag(DEBUG_ENV) if debug is None else debug
        # 隐私模式是 pywebview 的默认值，但真实应用里用户会期望 localStorage
        # 和 cookie 在重启后还在，所以默认关掉。
        self.private_mode = private_mode
        self.storage_path = Path(storage_path).expanduser() if storage_path else None

        self._web = Path(web).expanduser().resolve() if web else None
        self._windows: list[Window] = []
        # 窗口加载完成前发出的事件先攒着，等 ``loaded`` 事件到了再补发。
        self._pending_events: dict[str, list[tuple[str, Any]]] = {}
        self.router = Router(debug=self.debug)

        for handler in commands:
            self._register(handler)

    # -- 配置 ------------------------------------------------------------
    @classmethod
    def from_config(cls, path: str | os.PathLike[str] | None = None, **kwargs: Any) -> App:
        """按 ``[tool.cakeui]`` 建应用，标题默认取项目名。"""
        config = load_config(path)
        kwargs.setdefault("title", config.name)
        kwargs.setdefault("config", config)
        return cls(**kwargs)

    # -- 注册 ------------------------------------------------------------
    def command(
        self,
        func: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        validate_return: bool = True,
    ) -> Any:
        """注册命令，裸用（``@app.command``）和带括号调用都支持。"""

        def register(target: Callable[..., Any]) -> Callable[..., Any]:
            self.router.add_command(target, name=name, validate_return=validate_return)
            return target

        return register if func is None else register(func)

    def on(self, event: str, func: Callable[..., Any] | None = None) -> Any:
        """注册前端事件的 Python 处理函数。"""

        def register(target: Callable[..., Any]) -> Callable[..., Any]:
            self.router.add_event_handler(event, target)
            return target

        return register if func is None else register(func)

    def _register(self, entry: Any) -> None:
        # 已经用模块级 @command 建好 spec 的函数，直接复用，避免重复解析注解。
        spec = getattr(entry, "__cakeui_spec__", None)
        if isinstance(spec, CommandSpec):
            self.router.add_spec(spec)
        elif callable(entry):
            self.router.add_command(entry)
        else:
            raise TypeError(f"commands= 只接受装饰过的函数，收到 {type(entry).__name__}。")

    # -- 事件 ------------------------------------------------------------
    def emit(self, event: str, payload: Any = None) -> int:
        """向所有窗口广播事件，返回成功送达的窗口数。

        窗口还没加载完时，事件会先排队，等 ``loaded`` 之后再发，这样启动阶段
        运行的命令不会把事件丢掉。
        """
        return sum(1 for window in self._windows if self._emit_to_window(window, event, payload))

    def _emit_to_window(self, window: Window, event: str, payload: Any) -> bool:
        if not window.loaded:
            queue = self._pending_events.setdefault(window.id, [])
            if len(queue) < _MAX_PENDING_EVENTS:
                queue.append((event, payload))
            return False
        return self._deliver(window, event, payload)

    def _deliver(self, window: Window, event: str, payload: Any) -> bool:
        try:
            message = dumps({"event": event, "payload": payload})
        except TypeError as exc:
            raise CakeUIError(
                f"事件 {event!r} 的 payload 无法序列化为 JSON：{exc}",
                code="serialization_error",
            ) from exc

        script = f"window.__cakeui&&window.__cakeui._dispatch({js_string(message)})"
        try:
            window.native.evaluate_js(script)
        except Exception as exc:
            # 窗口正在关闭时投递失败是正常现象，只有 debug 模式才值得炸出来。
            if self.debug:
                raise CakeUIError(
                    f"无法把事件 {event!r} 投递到窗口 {window.id!r}：{exc}",
                    code="bridge_error",
                ) from exc
            return False
        return True

    def _flush_pending(self, window: Window) -> None:
        """窗口加载完成后，把排队的事件按顺序补发。"""
        for event, payload in self._pending_events.pop(window.id, []):
            try:
                self._deliver(window, event, payload)
            except CakeUIError:
                if self.debug:
                    raise

    # -- 窗口 ------------------------------------------------------------
    @property
    def windows(self) -> list[Window]:
        return list(self._windows)

    def create_window(
        self,
        *,
        title: str | None = None,
        url: str | None = None,
        width: int | None = None,
        height: int | None = None,
        resizable: bool | None = None,
    ) -> Window:
        """创建一个窗口；多窗口应用在 :meth:`run` 之前调用它。"""
        import webview  # 延迟导入，让 CLI 和测试不必加载 GUI 库

        api = _JsApi(self)
        native = webview.create_window(
            title if title is not None else self.title,
            url=url if url is not None else self._resolve_url(),
            width=width or self.width,
            height=height or self.height,
            min_size=self.min_size,
            resizable=self.resizable if resizable is None else resizable,
            background_color=self.background_color,
            js_api=api,
        )
        window = Window(native, self, window_id=f"w{len(self._windows) + 1}")
        api._bind(window)
        self._windows.append(window)
        return window

    def run(self, *, gui: str | None = None, debug: bool | None = None) -> None:
        """按需创建默认窗口，然后进入 pywebview 事件循环。"""
        import webview

        if not self._windows:
            self.create_window()

        webview.start(
            debug=self.debug if debug is None else debug,
            gui=gui or self.gui,
            private_mode=self.private_mode,
            storage_path=str(self.storage_path) if self.storage_path else None,
        )

    # -- 决定加载什么 ----------------------------------------------------
    def _resolve_url(self) -> str:
        """决定窗口该加载的 URL：显式地址优先，其次才是本地 index.html。"""
        explicit = (
            self.url
            or os.environ.get(DEV_URL_ENV)
            or (self.config.dev_url if self.config else None)
        )
        if explicit:
            return explicit

        entry = self._resolve_entry()
        if entry is None:
            raise ConfigError(
                "找不到要加载的 index.html。",
                details={
                    "hint": (
                        "设置 [tool.cakeui] web / web_dist，给 App() 传 web=，"
                        f"或者把 {DEV_URL_ENV} 指向开发服务器。"
                    ),
                    "searched": [str(path) for path in self._entry_candidates()],
                },
            )
        # 静态 HTML 需要旁边有个 cakeui.js 才能跑起来。
        ensure_bridge_file(entry.parent)
        return str(entry)

    def _entry_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        if self.config is not None:
            candidates.extend(directory / "index.html" for directory in self.config.web_candidates)
        if self._web is not None:
            candidates.append(self._web / "index.html")
        candidates.append(resource_root() / "index.html")
        return candidates

    def _resolve_entry(self) -> Path | None:
        for candidate in self._entry_candidates():
            if candidate.is_file():
                return candidate
        return None
