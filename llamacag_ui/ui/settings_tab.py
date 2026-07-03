"""Settings tab: cag-api URL, stack directory, chat defaults, welcome reset.

Apply writes everything through AppConfig and emits ``settings_applied`` so the
main window recreates the ApiClient and StackController against the new values.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..api_client import ApiClient
from ..config import DEFAULT_API_URL, AppConfig
from ..workers import run_in_pool
from .errors import message_for
from .toast import Toast


class SettingsTab(QWidget):
    settings_applied = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._build()
        self._load()

    # --- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        connection_box = QGroupBox("Connection")
        connection_form = QFormLayout(connection_box)
        api_row = QHBoxLayout()
        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText(DEFAULT_API_URL)
        api_row.addWidget(self.api_url_edit, 1)
        self.test_button = QPushButton("Test")
        self.test_button.clicked.connect(self._test_connection)
        api_row.addWidget(self.test_button)
        connection_form.addRow("cag-api base URL:", api_row)
        layout.addWidget(connection_box)

        stack_box = QGroupBox("Stack")
        stack_form = QFormLayout(stack_box)
        stack_row = QHBoxLayout()
        self.stack_dir_edit = QLineEdit()
        self.stack_dir_edit.setPlaceholderText("(none — pure client mode)")
        stack_row.addWidget(self.stack_dir_edit, 1)
        self.browse_button = QPushButton("Browse\N{HORIZONTAL ELLIPSIS}")
        self.browse_button.clicked.connect(self._browse_stack_dir)
        stack_row.addWidget(self.browse_button)
        self.detect_button = QPushButton("Auto-detect")
        self.detect_button.clicked.connect(self._autodetect)
        stack_row.addWidget(self.detect_button)
        stack_form.addRow("Stack directory:", stack_row)
        layout.addWidget(stack_box)

        chat_box = QGroupBox("Chat defaults")
        chat_form = QFormLayout(chat_box)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1, 8192)
        chat_form.addRow("Max tokens:", self.max_tokens_spin)
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        chat_form.addRow("Temperature:", self.temperature_spin)
        layout.addWidget(chat_box)

        welcome_row = QHBoxLayout()
        self.show_welcome_button = QPushButton("Show welcome dialog again")
        self.show_welcome_button.clicked.connect(self._reset_welcome)
        welcome_row.addWidget(self.show_welcome_button)
        welcome_row.addStretch(1)
        layout.addLayout(welcome_row)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)

        self.status_label = QLabel("")
        self.status_label.setProperty("mutedLabel", True)
        layout.addWidget(self.status_label)

    def _load(self) -> None:
        self.api_url_edit.setText(self._config.api_url)
        stack_dir = self._config.stack_dir
        self.stack_dir_edit.setText(str(stack_dir) if stack_dir else "")
        self.max_tokens_spin.setValue(self._config.max_tokens)
        self.temperature_spin.setValue(self._config.temperature)

    # --- actions -----------------------------------------------------------

    def _browse_stack_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select the llama-cag-n8n directory")
        if directory:
            self.stack_dir_edit.setText(directory)

    def _autodetect(self) -> None:
        from ..config import detect_stack_dir

        found = detect_stack_dir()
        if found is not None:
            self.stack_dir_edit.setText(str(found))
            Toast.success(self.window() or self, f"Found stack at {found}.")
        else:
            Toast.info(self.window() or self, "No sibling llama-cag-n8n directory found.")

    def _reset_welcome(self) -> None:
        self._config.show_welcome = True
        self._config.sync()
        Toast.info(self.window() or self, "Welcome dialog will show on next launch.")

    def _test_connection(self) -> None:
        url = self.api_url_edit.text().strip() or DEFAULT_API_URL
        self.test_button.setEnabled(False)
        self.status_label.setText(f"Testing {url}…")
        client = ApiClient(url)

        def done(report) -> None:
            client.close()
            self.test_button.setEnabled(True)
            self.status_label.setText(f"Connected — stack status: {report.status}.")
            Toast.success(self.window() or self, f"cag-api reachable ({report.status}).")

        def failed(_message, exc) -> None:
            client.close()
            self.test_button.setEnabled(True)
            self.status_label.setText(f"Failed: {message_for(exc)}")
            Toast.error(self.window() or self, message_for(exc))

        run_in_pool(client.health, on_finished=done, on_failed=failed)

    def apply(self) -> None:
        self._config.api_url = self.api_url_edit.text().strip()
        text = self.stack_dir_edit.text().strip()
        self._config.stack_dir = Path(text) if text else None
        self._config.max_tokens = self.max_tokens_spin.value()
        self._config.temperature = self.temperature_spin.value()
        self._config.sync()
        self.status_label.setText("Settings applied.")
        Toast.success(self.window() or self, "Settings applied.")
        self.settings_applied.emit()
