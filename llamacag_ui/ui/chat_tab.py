"""Chat tab: multi-turn Q&A against /query with per-answer cache badges.

The transcript is a widget-based bubble list (Qt rich text cannot render
rounded corners, so bubbles are real QFrames): user messages right-aligned in
amber-tinted panels, assistant messages left-aligned surface panels, and a
timings footer of pill chips under each answer. It exposes ``toPlainText()``
and ``clear()`` so it can be read like the QTextBrowser it replaced.

Sending disables the send button (the server serialises inference anyway) and
runs the query in a worker. History is the last MAX_HISTORY_TURNS turns.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..api_client import ApiClient, Document, QueryResult
from ..config import AppConfig
from ..workers import run_in_pool
from . import theme
from .errors import message_for
from .toast import Toast

# The server accepts up to 50 history turns; we send at most the last 20.
MAX_HISTORY_TURNS = 20

LATEST_LABEL = "(latest cached document)"

# Transcript empty-state hints (swapped based on whether cached docs exist).
PLACEHOLDER_PICK = "Pick a document and ask your first question."
PLACEHOLDER_NO_DOCS = "No cached documents yet — add one in the Documents tab."

_RECOMPUTED_ICON = "\N{CLOCKWISE RIGHTWARDS AND LEFTWARDS OPEN CIRCLE ARROWS}"
# cache_source -> (chip text, chip color): amber = memory heat, cyan = disk
# restore, red = recomputed from scratch.
_CACHE_BADGES = {
    "memory": ("\N{HIGH VOLTAGE SIGN} memory", theme.ACCENT),
    "disk": ("\N{FLOPPY DISK} disk", theme.CYAN),
    "recomputed": (f"{_RECOMPUTED_ICON} recomputed", theme.RED),
}
_CACHE_TOOLTIPS = {
    "memory": "Answered from KV state already resident in RAM — the fastest path.",
    "disk": "The document's KV state was restored from its cache file on disk first.",
    "recomputed": "No usable cache — the document was re-read once (slow), then re-saved.",
}

# role -> (bubble background, sender-label color)
_ROLE_STYLES = {
    "user": (theme.tint(theme.ACCENT, theme.WINDOW_BG, 0.14), theme.TEXT_MUTED),
    "assistant": (theme.SURFACE, theme.TEXT_MUTED),
    "error": (theme.tint(theme.RED, theme.WINDOW_BG, 0.14), theme.RED),
}

# QLabel wraps only at word boundaries, so a very long unbroken run (a URL, a
# base64 blob) would overflow its bubble. Insert zero-width spaces to give the
# wrap engine break opportunities; display-only, originals stay intact.
_LONG_RUN = re.compile(r"\S{48,}")


def _soften(text: str) -> str:
    def _break(match: re.Match[str]) -> str:
        run = match.group(0)
        return "​".join(run[i : i + 40] for i in range(0, len(run), 40))

    return _LONG_RUN.sub(_break, text)


class _ChatInput(QPlainTextEdit):
    """Enter sends; Shift+Enter inserts a newline."""

    send_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_requested.emit()
            return
        super().keyPressEvent(event)


class _Transcript(QScrollArea):
    """Bubble list with a QTextBrowser-compatible reading surface.

    ``toPlainText()`` returns the recorded conversation content (senders,
    texts, timing summaries) and ``clear()`` empties it — the same surface the
    tests and callers used against the previous QTextBrowser transcript.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatTranscript")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Bubbles hold no keyboard focus; tabbing skips straight to the input.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        body = QWidget()
        body.setObjectName("chatTranscriptBody")
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(12)  # vertical gap between messages
        self._layout.addStretch(1)
        self.setWidget(body)
        self._rows: list[QWidget] = []
        # (bubble frame, body label, text) per message, for width re-flow.
        self._entries: list[tuple[QFrame, QLabel, str]] = []
        self._plain: list[str] = []
        # Centered muted hint shown while the conversation is empty.
        self._placeholder = QLabel("", self.viewport())
        self._placeholder.setObjectName("emptyHint")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._update_placeholder()

    # --- QTextBrowser-compatible surface ------------------------------------

    def toPlainText(self) -> str:  # noqa: N802 - mirrors QTextBrowser's API
        return "\n".join(self._plain)

    def clear(self) -> None:
        for row in self._rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._entries.clear()
        self._plain.clear()
        self._update_placeholder()

    # --- empty state ---------------------------------------------------------

    def set_placeholder(self, text: str) -> None:
        self._placeholder.setText(text)
        self._update_placeholder()

    def _update_placeholder(self) -> None:
        self._placeholder.setVisible(not self._rows)
        self._placeholder.setGeometry(self.viewport().rect().adjusted(32, 0, -32, 0))

    # --- content -------------------------------------------------------------

    def add_bubble(
        self,
        who: str,
        text: str,
        role: str,
        footer: tuple[str, str, str, str] | None = None,
    ) -> None:
        """Append one message. ``footer`` is (chip_text, chip_color,
        chip_tooltip, summary) rendered as a pill chip + muted timing line."""
        bg, sender_color = _ROLE_STYLES.get(role, _ROLE_STYLES["assistant"])
        display_text = _soften(text)

        bubble = QFrame()
        bubble.setObjectName("bubble")
        bubble.setStyleSheet(f"#bubble {{ background-color: {bg}; border-radius: 12px; }}")
        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(14, 10, 14, 12)
        inner.setSpacing(4)

        sender = QLabel(who.upper())
        sender.setTextFormat(Qt.TextFormat.PlainText)
        sender.setStyleSheet(
            f"color: {sender_color}; font-size: 10px; font-weight: 700; "
            "letter-spacing: 1px; background: transparent;"
        )
        inner.addWidget(sender)

        body_label = QLabel(display_text)
        body_label.setTextFormat(Qt.TextFormat.PlainText)
        body_label.setWordWrap(True)
        body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; background: transparent;")
        inner.addWidget(body_label)

        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(6)
        align = Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft
        column_layout.addWidget(bubble, 0, align)
        self._plain.append(f"{who}\n{text}")

        if footer is not None:
            chip_text, chip_color, chip_tooltip, summary = footer
            column_layout.addWidget(self._footer_row(chip_text, chip_color, chip_tooltip, summary))
            self._plain.append(f"{chip_text} \N{MIDDLE DOT} {summary}")

        self._entries.append((bubble, body_label, display_text))
        self._apply_bubble_geometry(bubble, body_label, display_text)
        self._add_row(column, right=(role == "user"))

    def _footer_row(
        self, chip_text: str, chip_color: str, chip_tooltip: str, summary: str
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(8)
        chip = QLabel(chip_text)
        chip.setTextFormat(Qt.TextFormat.PlainText)
        chip.setStyleSheet(theme.chip_style(chip_color, theme.WINDOW_BG))
        if chip_tooltip:
            chip.setToolTip(chip_tooltip)
        layout.addWidget(chip)
        summary_label = QLabel(summary)
        summary_label.setTextFormat(Qt.TextFormat.PlainText)
        summary_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(summary_label)
        layout.addStretch(1)
        return row

    def _add_row(self, widget: QWidget, *, right: bool) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        if right:
            layout.addStretch(1)
            layout.addWidget(widget)
        else:
            layout.addWidget(widget)
            layout.addStretch(1)
        # Insert above the trailing stretch so messages flow top-down.
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._rows.append(row)
        self._update_placeholder()
        QTimer.singleShot(0, self._scroll_to_bottom)

    # --- geometry ------------------------------------------------------------

    def _max_bubble_width(self) -> int:
        return max(int(self.viewport().width() * 0.7), 280)

    def _apply_bubble_geometry(self, bubble: QFrame, label: QLabel, text: str) -> None:
        """Size the body label explicitly: natural width capped at ~70% of the
        viewport, with the wrapped height pinned via heightForWidth. A plain
        word-wrapped QLabel in nested layouts otherwise wraps narrow and can
        clip its last lines."""
        cap = self._max_bubble_width()
        inner_cap = max(cap - 28, 160)  # minus the bubble's 14px side margins
        metrics = label.fontMetrics()
        lines = text.splitlines() or [""]
        natural = max(metrics.horizontalAdvance(line) for line in lines) + 6
        width = min(natural, inner_cap)
        label.setFixedWidth(width)
        label.setMinimumHeight(max(label.heightForWidth(width), 0))
        bubble.setMaximumWidth(cap)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        for bubble, label, text in self._entries:
            self._apply_bubble_geometry(bubble, label, text)
        self._update_placeholder()

    def _scroll_to_bottom(self) -> None:
        try:
            bar = self.verticalScrollBar()
        except RuntimeError:  # widget already destroyed (app teardown race)
            return
        bar.setValue(bar.maximum())


class ChatTab(QWidget):
    """A single conversation. ``set_documents`` feeds the picker;
    ``set_send_enabled`` gates sending on stack health."""

    def __init__(
        self,
        client: ApiClient,
        config: AppConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._config = config
        self._history: list[dict[str, str]] = []
        self._documents: list[Document] = []
        self._sending = False
        self._health_ok = True
        self._last_answer = ""
        self._build()

    # --- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Document:"))
        self.document_combo = QComboBox()
        self.document_combo.addItem(LATEST_LABEL, None)
        self.document_combo.setToolTip(
            'Which cached document to ask — "(latest)" uses the most recently cached one.'
        )
        top.addWidget(self.document_combo, 1)

        top.addWidget(QLabel("Max tokens:"))
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1, 8192)
        self.max_tokens_spin.setValue(self._config.max_tokens)
        self.max_tokens_spin.setToolTip("Longest answer to generate, in tokens.")
        top.addWidget(self.max_tokens_spin)

        top.addWidget(QLabel("Temp:"))
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(self._config.temperature)
        self.temperature_spin.setToolTip(
            "Sampling temperature — 0 is deterministic, higher is more varied."
        )
        top.addWidget(self.temperature_spin)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_conversation)
        top.addWidget(self.clear_button)
        layout.addLayout(top)

        self.transcript = _Transcript()
        self.transcript.set_placeholder(PLACEHOLDER_PICK)
        layout.addWidget(self.transcript, 1)

        self.status_label = QLabel("")
        self.status_label.setProperty("mutedLabel", True)
        self.status_label.setVisible(False)  # only shown when there is a message
        layout.addWidget(self.status_label)

        bottom = QHBoxLayout()
        self.input = _ChatInput()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("Ask a question…  (Enter to send, Shift+Enter for newline)")
        self.input.setFixedHeight(96)
        self.input.send_requested.connect(self.send)
        bottom.addWidget(self.input, 1)

        side = QVBoxLayout()
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self.send)
        side.addWidget(self.send_button)
        self.copy_button = QPushButton("Copy answer")
        self.copy_button.clicked.connect(self._copy_last_answer)
        self.copy_button.setEnabled(False)
        side.addWidget(self.copy_button)
        bottom.addLayout(side)
        layout.addLayout(bottom)

        # Sensible keyboard path: params first, then straight to the input.
        QWidget.setTabOrder(self.document_combo, self.max_tokens_spin)
        QWidget.setTabOrder(self.max_tokens_spin, self.temperature_spin)
        QWidget.setTabOrder(self.temperature_spin, self.clear_button)
        QWidget.setTabOrder(self.clear_button, self.input)
        QWidget.setTabOrder(self.input, self.send_button)
        QWidget.setTabOrder(self.send_button, self.copy_button)

        self._refresh_send_enabled()

    # --- client swap -------------------------------------------------------

    def set_client(self, client: ApiClient) -> None:
        self._client = client

    # --- document picker ---------------------------------------------------

    def set_documents(self, documents: list[Document]) -> None:
        """Repopulate the picker with cached documents, preserving selection."""
        previous = self.document_combo.currentData()
        self._documents = documents
        self.document_combo.blockSignals(True)
        self.document_combo.clear()
        self.document_combo.addItem(LATEST_LABEL, None)
        cached = 0
        for doc in documents:
            if doc.status == "cached":
                self.document_combo.addItem(f"#{doc.id}  {doc.file_name}", doc.id)
                cached += 1
        index = self.document_combo.findData(previous)
        self.document_combo.setCurrentIndex(index if index >= 0 else 0)
        self.document_combo.blockSignals(False)
        self.transcript.set_placeholder(PLACEHOLDER_PICK if cached else PLACEHOLDER_NO_DOCS)

    # --- health gating -----------------------------------------------------

    def set_send_enabled(self, ok: bool) -> None:
        self._health_ok = ok
        self._refresh_send_enabled()

    def _refresh_send_enabled(self) -> None:
        can_send = self._health_ok and not self._sending
        self.send_button.setEnabled(can_send)
        if not self._health_ok:
            self.status_label.setText(
                "Stack unavailable — start it on the Stack tab, then try again."
            )
        elif self._sending:
            self.status_label.setText("Generating… (large contexts can take a while)")
        else:
            self.status_label.setText("")
        # Hidden when empty so it doesn't reserve a dead band above the input.
        self.status_label.setVisible(bool(self.status_label.text()))

    # --- sending -----------------------------------------------------------

    def send(self) -> None:
        if self._sending or not self._health_ok:
            return
        question = self.input.toPlainText().strip()
        if not question:
            return

        self.input.clear()
        self.transcript.add_bubble("You", question, "user")
        document_id = self.document_combo.currentData()

        self._sending = True
        self._refresh_send_enabled()

        run_in_pool(
            self._client.query,
            question,
            document_id=document_id,
            max_tokens=self.max_tokens_spin.value(),
            temperature=self.temperature_spin.value(),
            history=self._history[-MAX_HISTORY_TURNS:] or None,
            on_finished=lambda result: self._on_answer(question, result),
            on_failed=self._on_query_failed,
        )
        # Keep the caret in the input so the next question can be typed at once.
        self.input.setFocus()

    def _on_answer(self, question: str, result: QueryResult) -> None:
        self._sending = False
        self._refresh_send_enabled()

        self._history.append({"role": "user", "content": question})
        self._history.append({"role": "assistant", "content": result.answer})

        t = result.timings
        chip_text, chip_color = _CACHE_BADGES.get(
            t.cache_source, (t.cache_source, theme.TEXT_MUTED)
        )
        chip_tooltip = _CACHE_TOOLTIPS.get(t.cache_source, "")
        summary = (
            f"{_fmt(t.prompt_tokens_evaluated)} tok evaluated / "
            f"{_fmt(t.prompt_tokens_from_cache)} cached / "
            f"{_fmt(t.answer_tokens)} answer \N{MIDDLE DOT} {result.duration_ms} ms"
        )
        self.transcript.add_bubble(
            "Assistant",
            result.answer,
            "assistant",
            footer=(chip_text, chip_color, chip_tooltip, summary),
        )
        self._last_answer = result.answer
        self.copy_button.setEnabled(True)

    def _on_query_failed(self, message: str, exc: Exception) -> None:
        self._sending = False
        self._refresh_send_enabled()
        # Errors are chat bubbles with the API detail, and history is preserved.
        self.transcript.add_bubble("Error", message_for(exc), "error")

    # --- actions -----------------------------------------------------------

    def clear_conversation(self) -> None:
        self._history.clear()
        self.transcript.clear()
        self._last_answer = ""
        self.copy_button.setEnabled(False)

    def _copy_last_answer(self) -> None:
        if not self._last_answer:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._last_answer)
        Toast.info(self.window() or self, "Answer copied to clipboard.")


def _fmt(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"
