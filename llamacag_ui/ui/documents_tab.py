"""Documents tab: upload / warm / list / delete, with drag-drop.

The table is the source of truth the poller refreshes. All slow calls (list,
upload, delete) go through ``run_in_pool``; the tab never blocks and never
touches the network directly beyond handing the client method to a worker.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..api_client import ApiClient, Document
from ..workers import run_in_pool
from . import theme
from .errors import message_for
from .toast import Toast

# Extensions the backend can extract (mirrors extract.SUPPORTED_EXTENSIONS).
SUPPORTED_EXTENSIONS = {".txt", ".text", ".md", ".markdown", ".html", ".htm", ".pdf"}

# status -> chip color (green cached, amber pending, red failed).
_STATUS_COLORS = {
    "cached": theme.GREEN,
    "pending": theme.ACCENT,
    "failed": theme.RED,
}

_COLUMNS = ["ID", "File name", "Status", "Tokens", "Size fit", "Last used", "Uses"]


def _short_ts(value: str | None) -> str:
    if not value:
        return "—"
    # ISO 8601 "2026-07-02T12:00:00+00:00" -> "2026-07-02 12:00"
    text = value.replace("T", " ")
    return text[:16]


class DocumentsTab(QWidget):
    """Table + toolbar. ``documents_changed`` fires whenever the list is
    (re)loaded so the chat tab can refresh its document picker."""

    documents_changed = Signal(list)  # list[Document]
    busy_changed = Signal(bool)

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._documents: list[Document] = []
        self._busy = False
        self.setAcceptDrops(True)
        self._build()

    # --- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.upload_button = QPushButton("Upload\N{HORIZONTAL ELLIPSIS}")
        self.upload_button.clicked.connect(self._choose_and_upload)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setEnabled(False)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.upload_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addWidget(self.refresh_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)  # subtle row separators come from the theme
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # Centered invitation shown while the table is empty.
        self.empty_label = QLabel(
            "No documents yet — drag a file anywhere here, or click Upload.",
            self.table.viewport(),
        )
        self.empty_label.setObjectName("emptyHint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._update_empty_state()

        self.hint_label = _drop_hint()
        layout.addWidget(self.hint_label)

    def _update_empty_state(self) -> None:
        self.empty_label.setVisible(self.table.rowCount() == 0)
        self.empty_label.setGeometry(self.table.viewport().rect().adjusted(24, 0, -24, 0))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._update_empty_state()

    # --- client swap (settings changed) ------------------------------------

    def set_client(self, client: ApiClient) -> None:
        self._client = client

    # --- busy state --------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.upload_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy and self.table.currentRow() >= 0)
        self.busy_changed.emit(busy)

    # --- refresh -----------------------------------------------------------

    def refresh(self) -> None:
        """Reload the document list off-thread. Safe to call from the poller."""
        if self._busy:
            return
        run_in_pool(
            self._client.list_documents,
            on_finished=self._populate,
            on_failed=self._on_error,
        )

    def _populate(self, documents: list[Document]) -> None:
        self._documents = documents
        self.table.setRowCount(len(documents))
        for row, doc in enumerate(documents):
            self._fill_row(row, doc)
        self.table.resizeColumnsToContents()
        # Status chips are cell widgets, invisible to resizeColumnsToContents.
        self.table.setColumnWidth(2, max(self.table.columnWidth(2), 96))
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._update_empty_state()
        self.documents_changed.emit(documents)

    def _fill_row(self, row: int, doc: Document) -> None:
        values = [
            str(doc.id),
            doc.file_name,
            None,  # status column is a chip widget, not an item
            "—" if doc.n_tokens is None else f"{doc.n_tokens:,}",
            self._fit_text(doc),
            _short_ts(doc.last_used_at),
            str(doc.use_count),
        ]
        for col, text in enumerate(values):
            if text is None:
                continue
            item = QTableWidgetItem(text)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, doc.id)
            if col == 1:
                # Long names elide in the stretch column; keep the full name.
                item.setToolTip(doc.file_name)
            self.table.setItem(row, col, item)
        self.table.setCellWidget(row, 2, self._status_chip(doc))

    @staticmethod
    def _status_chip(doc: Document) -> QWidget:
        """A pill chip for the status column: colored text on a tinted bg."""
        chip = QLabel(doc.status)
        chip.setTextFormat(Qt.TextFormat.PlainText)
        color = _STATUS_COLORS.get(doc.status, theme.TEXT_MUTED)
        chip.setStyleSheet(theme.chip_style(color))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.addWidget(chip)
        layout.addStretch(1)
        if doc.status == "failed" and doc.error:
            chip.setToolTip(doc.error)
            container.setToolTip(doc.error)
        return container

    @staticmethod
    def _fit_text(doc: Document) -> str:
        # The server enforces the real limit; here we only echo cached/failed
        # so the user sees at a glance whether the document made it in.
        if doc.status == "cached":
            return "fits"
        if doc.status == "failed":
            return "rejected"
        return "checking…"

    # --- selection ---------------------------------------------------------

    def _on_selection_changed(self) -> None:
        self.delete_button.setEnabled(not self._busy and self.table.currentRow() >= 0)

    def _selected_document(self) -> Document | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._documents):
            return None
        return self._documents[row]

    # --- upload ------------------------------------------------------------

    def _choose_and_upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose documents to upload",
            "",
            "Documents (*.txt *.text *.md *.markdown *.html *.htm *.pdf);;All files (*)",
        )
        for path in paths:
            self.upload_path(Path(path))

    def upload_path(self, path: Path) -> None:
        """Upload a single file by path (used by the dialog and by drag-drop)."""
        try:
            data = path.read_bytes()
        except OSError as exc:
            Toast.error(self._toast_parent(), f"Could not read {path.name}: {exc}")
            return
        self._set_busy(True)
        Toast.info(
            self._toast_parent(),
            f"Uploading {path.name} and warming it (can take minutes on CPU)…",
        )
        run_in_pool(
            self._client.upload_document,
            path.name,
            data,
            on_finished=self._on_uploaded,
            on_failed=self._on_upload_failed,
        )

    def _on_uploaded(self, doc: Document) -> None:
        self._set_busy(False)
        if doc.deduplicated:
            Toast.info(
                self._toast_parent(),
                f"{doc.file_name} was already ingested (document #{doc.id}).",
            )
        else:
            Toast.success(self._toast_parent(), f"Cached {doc.file_name} (document #{doc.id}).")
        self.refresh()

    def _on_upload_failed(self, message: str, exc: Exception) -> None:
        self._set_busy(False)
        Toast.error(self._toast_parent(), message_for(exc))
        self.refresh()

    # --- delete ------------------------------------------------------------

    def _delete_selected(self) -> None:
        doc = self._selected_document()
        if doc is None:
            return
        from PySide6.QtWidgets import QMessageBox

        confirm = QMessageBox.question(
            self,
            "Delete document",
            f"Delete “{doc.file_name}” (document #{doc.id}) and its cache?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        run_in_pool(
            self._client.delete_document,
            doc.id,
            on_finished=lambda _id: self._on_deleted(doc),
            on_failed=self._on_error_after_busy,
        )

    def _on_deleted(self, doc: Document) -> None:
        self._set_busy(False)
        Toast.success(self._toast_parent(), f"Deleted {doc.file_name}.")
        self.refresh()

    # --- error helpers -----------------------------------------------------

    def _on_error(self, message: str, exc: Exception) -> None:
        Toast.error(self._toast_parent(), message_for(exc))

    def _on_error_after_busy(self, message: str, exc: Exception) -> None:
        self._set_busy(False)
        self._on_error(message, exc)

    def _toast_parent(self) -> QWidget:
        return self.window() or self

    # --- drag & drop -------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt override
        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        accepted = False
        for path in paths:
            if path.is_file():
                self.upload_path(path)
                accepted = True
        if accepted:
            event.acceptProposedAction()
        else:
            event.ignore()


def _drop_hint() -> QLabel:
    # Styled as a dashed-border strip by the theme (QLabel#dropHint).
    label = QLabel("Drag files here or use Upload. Supported: txt, md, html, pdf.")
    label.setObjectName("dropHint")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label
