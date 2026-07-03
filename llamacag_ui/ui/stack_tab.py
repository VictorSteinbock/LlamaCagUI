"""Stack tab: health cards, hot slots, maintenance, and (optional) control.

Health cards and the hot-slots list are fed by the main window's poller via
``update_health``. Maintenance runs through the ApiClient. The control and
model-switch groups are enabled only when a StackController reports
``available()`` — otherwise they show why they are disabled and the app keeps
working as a pure client.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..api_client import ApiClient, HealthReport, MaintenanceReport
from ..models_catalog import CATALOG
from ..stack import StackController, StackError
from ..workers import run_in_pool
from . import theme
from .errors import message_for
from .toast import Toast

MODEL_SWITCH_WARNING = (
    "Switching the model recreates llama-server. Existing document caches were "
    "built for the old model and will re-heal (recompute once) on next use.\n\n"
    "Continue?"
)


class _HealthCard(QFrame):
    """One service's status card: a 4px colored left border (green ok / amber
    unknown-degraded / red down), the service name, and a detail line."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("healthCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)
        self._detail = QLabel("unknown")
        self._detail.setWordWrap(True)
        self._detail.setProperty("mutedLabel", True)
        layout.addWidget(self._detail)
        self.set_state(None, "unknown")

    def set_state(self, ok: bool | None, detail: str) -> None:
        if ok is None:
            color = theme.ACCENT  # unknown / degraded dependency
        elif ok:
            color = theme.GREEN
        else:
            color = theme.RED
        self.setStyleSheet(
            f"#healthCard {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER}; border-left: 4px solid {color};"
            " border-radius: 10px; }"
        )
        self._detail.setText(detail)


class StackTab(QWidget):
    def __init__(
        self,
        client: ApiClient,
        controller: StackController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._controller = controller
        self._build()
        self._sync_control_availability()

    # --- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        cards = QHBoxLayout()
        self.api_card = _HealthCard("cag-api")
        self.llama_card = _HealthCard("llama-server")
        self.db_card = _HealthCard("database")
        cards.addWidget(self.api_card)
        cards.addWidget(self.llama_card)
        cards.addWidget(self.db_card)
        layout.addLayout(cards)

        hot_box = QGroupBox("Hot documents (KV state resident per slot)")
        hot_layout = QVBoxLayout(hot_box)
        self.hot_label = QLabel("—")
        self.hot_label.setWordWrap(True)
        hot_layout.addWidget(self.hot_label)
        layout.addWidget(hot_box)

        maint_box = QGroupBox("Maintenance")
        maint_layout = QVBoxLayout(maint_box)
        maint_row = QHBoxLayout()
        self.maintenance_button = QPushButton("Run maintenance")
        self.maintenance_button.clicked.connect(self._run_maintenance)
        maint_row.addWidget(self.maintenance_button)
        maint_row.addStretch(1)
        maint_layout.addLayout(maint_row)
        self.maintenance_report = QLabel("Reconcile cache files with the registry.")
        self.maintenance_report.setObjectName("maintenanceReport")
        self.maintenance_report.setWordWrap(True)
        self.maintenance_report.setTextFormat(Qt.TextFormat.RichText)
        maint_layout.addWidget(self.maintenance_report)
        layout.addWidget(maint_box)

        layout.addWidget(self._build_control_group())
        layout.addWidget(self._build_model_group())
        layout.addStretch(1)

    def _build_control_group(self) -> QGroupBox:
        box = QGroupBox("Stack control")
        outer = QVBoxLayout(box)
        row = QHBoxLayout()
        self.start_button = QPushButton("Start stack")
        self.start_button.setObjectName("startButton")
        self.start_button.clicked.connect(self._start_stack)
        self.stop_button = QPushButton("Stop stack")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self._stop_stack)
        self.status_button = QPushButton("Refresh status")
        self.status_button.clicked.connect(self._refresh_status)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.status_button)
        row.addStretch(1)
        outer.addLayout(row)
        self.control_hint = QLabel("")
        self.control_hint.setProperty("mutedLabel", True)
        self.control_hint.setWordWrap(True)
        outer.addWidget(self.control_hint)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("stackLog")
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("docker compose output appears here…")
        self.log_view.setFixedHeight(120)
        outer.addWidget(self.log_view)
        self._control_box = box
        return box

    def _build_model_group(self) -> QGroupBox:
        box = QGroupBox("Model")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("Current:"), 0, 0)
        self.current_model_label = QLabel("—")
        grid.addWidget(self.current_model_label, 0, 1, 1, 2)

        grid.addWidget(QLabel("Curated:"), 1, 0)
        self.model_combo = QComboBox()
        for entry in CATALOG:
            self.model_combo.addItem(
                f"{entry.label} — {entry.context} ctx, {entry.size}", entry.repo
            )
        self.model_combo.currentIndexChanged.connect(self._on_catalog_pick)
        grid.addWidget(self.model_combo, 1, 1, 1, 2)

        grid.addWidget(QLabel("Or repo:"), 2, 0)
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("user/repo[:quant]")
        grid.addWidget(self.model_edit, 2, 1)
        self.apply_model_button = QPushButton("Apply model")
        self.apply_model_button.clicked.connect(self._apply_model)
        grid.addWidget(self.apply_model_button, 2, 2)

        self.model_desc = QLabel("")
        self.model_desc.setWordWrap(True)
        self.model_desc.setProperty("mutedLabel", True)
        grid.addWidget(self.model_desc, 3, 0, 1, 3)
        self._model_box = box
        self._on_catalog_pick(0)
        return box

    # --- client / controller swap ------------------------------------------

    def set_client(self, client: ApiClient) -> None:
        self._client = client

    def set_stack_controller(self, controller: StackController) -> None:
        self._controller = controller
        self._sync_control_availability()

    def _sync_control_availability(self) -> None:
        available = self._controller.available()
        for button in (self.start_button, self.stop_button, self.status_button):
            button.setEnabled(available)
        self.apply_model_button.setEnabled(available)
        self.model_combo.setEnabled(available)
        self.model_edit.setEnabled(available)
        reason = self._controller.unavailable_reason()
        self.control_hint.setText("" if available else (reason or "Stack control unavailable."))
        self._refresh_current_model()

    def _refresh_current_model(self) -> None:
        try:
            current = self._controller.current_model() if self._controller.available() else None
        except OSError:
            current = None
        self.current_model_label.setText(current or "—")

    # --- health feed (from poller) -----------------------------------------

    def update_health(self, report: HealthReport | None) -> None:
        if report is None or report.status == "unreachable":
            detail = "cag-api unreachable"
            self.api_card.set_state(False, detail)
            self.llama_card.set_state(None, "unknown")
            self.db_card.set_state(None, "unknown")
            self.hot_label.setText("—")
            return

        self.api_card.set_state(True, f"reachable · status: {report.status}")
        self.llama_card.set_state(
            report.llama_ok,
            "ok" if report.llama_ok else str(report.llama_server.get("error", "error")),
        )
        self.db_card.set_state(
            report.db_ok,
            "ok" if report.db_ok else str(_db_error(report.database)),
        )
        self._render_hot(report)

    def _render_hot(self, report: HealthReport) -> None:
        if not report.hot_documents:
            self.hot_label.setText(f"No documents hot (0 of {report.slots} slots in use).")
            return
        lines = [
            f"slot {slot}: document #{doc}"
            for slot, doc in sorted(report.hot_documents.items())
        ]
        self.hot_label.setText(
            f"{len(report.hot_documents)} of {report.slots} slots hot — " + ", ".join(lines)
        )

    # --- maintenance -------------------------------------------------------

    def _run_maintenance(self) -> None:
        self.maintenance_button.setEnabled(False)
        self.maintenance_report.setText("Running maintenance…")
        run_in_pool(
            self._client.maintenance,
            on_finished=self._on_maintenance,
            on_failed=self._on_maintenance_failed,
        )

    def _on_maintenance(self, report: MaintenanceReport) -> None:
        self.maintenance_button.setEnabled(True)
        mb = report.cache_bytes / (1024 * 1024)
        rows = [
            ("Orphan files removed", len(report.orphan_files_removed)),
            ("Orphan removals failed", len(report.orphan_files_failed)),
            ("Missing cache files", len(report.missing_cache_files)),
            ("Cache files on disk", report.cache_files),
            ("Cache size", f"{mb:.1f} MB"),
            ("Documents", report.documents),
            ("Cached documents", report.cached_documents),
            ("Queries (24h)", report.queries_24h),
            ("Avg duration (24h)", f"{report.avg_duration_ms_24h} ms"),
        ]
        html_rows = "".join(
            f'<tr><td style="padding-right:16px; color:{theme.TEXT_MUTED};">{k}</td>'
            f'<td style="color:{theme.TEXT};"><b>{v}</b></td></tr>'
            for k, v in rows
        )
        self.maintenance_report.setText(f"<table>{html_rows}</table>")
        Toast.success(self.window() or self, "Maintenance complete.")

    def _on_maintenance_failed(self, message: str, exc: Exception) -> None:
        self.maintenance_button.setEnabled(True)
        self.maintenance_report.setText(f"Maintenance failed: {message_for(exc)}")
        Toast.error(self.window() or self, message_for(exc))

    # --- stack control -----------------------------------------------------

    def _start_stack(self) -> None:
        self._run_control("start", self._controller.start, "Starting stack…")

    def _stop_stack(self) -> None:
        self._run_control("stop", self._controller.stop, "Stopping stack…")

    def _run_control(self, name: str, fn, message: str) -> None:
        self._set_control_enabled(False)
        self.log_view.appendPlainText(f"$ {message}")

        def done(output: str) -> None:
            self._set_control_enabled(True)
            Toast.success(self.window() or self, f"Stack {name} complete.")

        def failed(_message, exc) -> None:
            self._set_control_enabled(True)
            self.log_view.appendPlainText(f"error: {message_for(exc)}")
            Toast.error(self.window() or self, message_for(exc))

        # The Worker injects on_progress into fn (StackController.start/stop/
        # restart_llama accept it); each line is marshalled to the UI thread.
        run_in_pool(
            fn,
            on_finished=done,
            on_failed=failed,
            on_progress=self.log_view.appendPlainText,
        )

    def _refresh_status(self) -> None:
        self.status_button.setEnabled(False)

        def done(output: str) -> None:
            self.status_button.setEnabled(True)
            self.log_view.appendPlainText(output or "(no services running)")

        def failed(_message, exc) -> None:
            self.status_button.setEnabled(True)
            self.log_view.appendPlainText(f"error: {message_for(exc)}")

        run_in_pool(self._controller.ps, on_finished=done, on_failed=failed)

    def _set_control_enabled(self, enabled: bool) -> None:
        available = self._controller.available()
        for button in (self.start_button, self.stop_button, self.status_button):
            button.setEnabled(enabled and available)

    # --- model switch ------------------------------------------------------

    def _on_catalog_pick(self, _index: int) -> None:
        from ..models_catalog import find

        repo = self.model_combo.currentData()
        entry = find(repo) if repo else None
        self.model_desc.setText(entry.description if entry else "")

    def _apply_model(self) -> None:
        repo = self.model_edit.text().strip() or self.model_combo.currentData()
        if not repo:
            Toast.error(self.window() or self, "Choose a model or enter a repo spec.")
            return
        from PySide6.QtWidgets import QMessageBox

        confirm = QMessageBox.warning(
            self,
            "Switch model",
            f"Switch to “{repo}”?\n\n{MODEL_SWITCH_WARNING}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            self._controller.set_model(repo)
        except StackError as exc:
            Toast.error(self.window() or self, str(exc))
            return

        self._refresh_current_model()
        Toast.info(self.window() or self, f"Model set to {repo}; restarting llama-server…")
        self._run_control(
            "model restart", self._controller.restart_llama, "Restarting llama-server…"
        )


def _db_error(database) -> str:
    if isinstance(database, dict):
        return database.get("error", "error")
    return str(database)
