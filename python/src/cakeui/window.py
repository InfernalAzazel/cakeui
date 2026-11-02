"""pywebview 窗口的一层薄封装，方便测试和类型提示。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import WindowNotReadyError

if TYPE_CHECKING:  # pragma: no cover
    from .app import App


class Window:
    """传给声明了 ``window`` 参数的命令的窗口句柄。

    这个对象刻意保持很小：只暴露 CakeUI 能在 pywebview 之上真正保证的几件事，
    其余能力都可以通过 :attr:`native` 直接拿到底层窗口。
    """

    def __init__(self, native: Any, app: App, *, window_id: str = "main") -> None:
        self._native = native
        self._app = app
        self.id = window_id

        # 页面加载完成前发出的事件由 App 排队；这里挂上 pywebview 的 loaded
        # 事件，等窗口就绪后立刻补发。
        loaded = getattr(getattr(native, "events", None), "loaded", None)
        if loaded is not None:
            loaded += self._on_loaded

    def _on_loaded(self, *_args: Any) -> None:
        self._app._flush_pending(self)

    # -- 读取状态 --------------------------------------------------------
    @property
    def native(self) -> Any:
        """底层的 ``webview.Window`` 实例。"""
        return self._native

    @property
    def title(self) -> str:
        return getattr(self._native, "title", "") or ""

    @title.setter
    def title(self, value: str) -> None:
        self._native.title = value

    @property
    def loaded(self) -> bool:
        """页面是否已加载完成（此时 ``pywebview.api`` 才存在）。"""
        events = getattr(self._native, "events", None)
        loaded = getattr(events, "loaded", None)
        return bool(loaded is not None and loaded.is_set())

    # -- 和页面通信 ------------------------------------------------------
    def emit(self, event: str, payload: Any = None) -> bool:
        """只把事件发给这个窗口里注册的 JS 监听器。"""
        return self._app._emit_to_window(self, event, payload)

    def evaluate(self, script: str) -> Any:
        """在这个窗口里执行一段 JS 表达式并返回结果。"""
        try:
            return self._native.evaluate_js(script)
        except Exception as exc:  # pywebview 这里会抛各种异常，统一归一化
            raise WindowNotReadyError(f"无法在窗口 {self.id!r} 里执行 JS：{exc}") from exc

    # -- 窗口控制 --------------------------------------------------------
    def show(self) -> None:
        self._native.show()

    def hide(self) -> None:
        self._native.hide()

    def close(self) -> None:
        self._native.destroy()
