"""Transient toast notifications (ported from v1, PySide6).

A small frameless label that fades in over its parent, sits for a few seconds,
then fades out and deletes itself. Two variants — success and error — plus a
neutral default. Stateless: call ``Toast.show_message(parent, text)`` and forget.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from . import theme

# variant -> (background, text, border)
_VARIANT_COLORS = {
    "default": (theme.ELEVATED, theme.TEXT, theme.BORDER),
    "success": (theme.GREEN, theme.WINDOW_BG, theme.GREEN),
    "error": (theme.RED, theme.WINDOW_BG, theme.RED),
    "info": (theme.CYAN, theme.WINDOW_BG, theme.CYAN),
}


class Toast(QLabel):
    """A fading notification pinned near the bottom of its parent."""

    def __init__(
        self,
        parent: QWidget,
        message: str,
        *,
        variant: str = "default",
        timeout_ms: int = 3200,
    ) -> None:
        super().__init__(message, parent)
        self._timeout_ms = timeout_ms
        bg, fg, border = _VARIANT_COLORS.get(variant, _VARIANT_COLORS["default"])

        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMaximumWidth(420)
        self.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            "border-radius: 10px; padding: 10px 16px; "
            "font-size: 13px; font-weight: 600;"
        )

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade: QPropertyAnimation | None = None

    # --- lifecycle ---------------------------------------------------------

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        rect = parent.rect()
        x = rect.width() // 2 - self.width() // 2
        y = rect.height() - self.height() - 48
        self.move(max(x, 12), max(y, 12))

    def popup(self) -> None:
        self._reposition()
        self.show()
        self.raise_()
        self._animate(0.0, 1.0, on_done=self._schedule_dismiss)

    def _schedule_dismiss(self) -> None:
        QTimer.singleShot(self._timeout_ms, self._fade_out)

    def _fade_out(self) -> None:
        self._animate(1.0, 0.0, on_done=self.deleteLater)

    def _animate(self, start: float, end: float, *, on_done) -> None:
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(on_done)
        anim.start()
        self._fade = anim  # keep a reference so it is not GC'd mid-flight

    # --- convenience -------------------------------------------------------

    @classmethod
    def show_message(
        cls,
        parent: QWidget,
        message: str,
        *,
        variant: str = "default",
        timeout_ms: int = 3200,
    ) -> Toast:
        toast = cls(parent, message, variant=variant, timeout_ms=timeout_ms)
        toast.popup()
        return toast

    @classmethod
    def success(cls, parent: QWidget, message: str) -> Toast:
        return cls.show_message(parent, message, variant="success")

    @classmethod
    def error(cls, parent: QWidget, message: str) -> Toast:
        return cls.show_message(parent, message, variant="error", timeout_ms=5000)

    @classmethod
    def info(cls, parent: QWidget, message: str) -> Toast:
        return cls.show_message(parent, message, variant="info")
