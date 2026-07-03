"""First-run welcome dialog: what CAG is, and how to get to a first answer.

Gated by ``AppConfig.show_welcome``; a "don't show again" checkbox writes the
flag back. A hero header (app name + tagline), a three-paragraph CAG explainer,
and four quickstart steps as numbered amber circles.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from . import theme

STACK_README_URL = "https://github.com/VictorSteinbock/llama-cag-n8n#readme"

TAGLINE = "Read once. Ask forever."

_INTRO_HTML = f"""
<p>LlamaCag UI lets you <b>chat with your documents</b>. It is a thin desktop
client of the <i>llama-cag-n8n</i> stack, which runs a local language model over
your whole document at once.</p>
<p><span style="color: {theme.ACCENT}; font-weight: 600;">Cache-Augmented
Generation (CAG)</span> feeds the entire document into the model once and keeps
that work — the model's KV cache — resident in memory. Every later question
reuses it, so answers are grounded in <i>your</i> document and come back fast
without re-reading it each time.</p>
<p>Unlike snippet-retrieval (RAG), nothing is chunked or searched: the model
sees the full text, and is told to answer only from it.</p>
"""

# (title, body) quickstart steps, rendered as numbered amber circles.
_STEPS = [
    (
        "Start the stack",
        "On the <b>Stack</b> tab, check that cag-api, llama-server and the "
        "database are healthy. If a stack directory is configured you can "
        "start it right here.",
    ),
    (
        "Add a document",
        "On the <b>Documents</b> tab, drag a file onto the table or click "
        "<b>Upload</b>. Status goes <i>pending</i> &rarr; <i>cached</i> — "
        "warming a large document can take minutes on CPU.",
    ),
    (
        "Ask",
        'On the <b>Chat</b> tab, pick the document (or leave "(latest)"), '
        "type a question, and press Enter.",
    ),
    (
        "Read the badge",
        "Each answer shows where its context came from — &#9889; memory, "
        "&#128190; disk, or &#128257; recomputed — and how many tokens were "
        "evaluated versus reused.",
    ),
]


def _steps_html() -> str:
    rows = []
    for index, (title, body) in enumerate(_STEPS, start=1):
        circle = chr(0x2775 + index)  # ❶ ❷ ❸ ❹ — negative circled digits
        rows.append(
            f'<tr><td style="padding: 6px 10px 6px 0; color: {theme.ACCENT}; '
            f'font-size: 17px;" valign="top">{circle}</td>'
            f'<td style="padding: 6px 0;"><b>{title}.</b> {body}</td></tr>'
        )
    return f'<table cellspacing="0" cellpadding="0">{"".join(rows)}</table>'


class WelcomeDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Welcome to LlamaCag UI")
        self.setMinimumSize(660, 620)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 20)
        layout.setSpacing(14)

        title = QLabel("LlamaCag UI")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        tagline = QLabel(TAGLINE)
        tagline.setObjectName("heroTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        intro = QLabel(_INTRO_HTML)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)

        steps = QLabel(_steps_html())
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(steps)

        link = QLabel(f'<a href="{STACK_README_URL}">About the llama-cag-n8n stack &rarr;</a>')
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        layout.addStretch(1)

        self._dont_show = QCheckBox("Don't show this again")
        self._dont_show.setChecked(not self._config.show_welcome)
        layout.addWidget(self._dont_show)

        buttons = QDialogButtonBox()
        get_started = buttons.addButton("Get started", QDialogButtonBox.ButtonRole.AcceptRole)
        get_started.setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def accept(self) -> None:
        # Checkbox checked -> stop showing; unchecked -> keep showing next run.
        self._config.show_welcome = not self._dont_show.isChecked()
        self._config.sync()
        super().accept()
