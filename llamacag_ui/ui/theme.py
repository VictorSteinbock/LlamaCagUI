"""Visual identity: palette constants, the application stylesheet, apply_theme.

ALL static styling lives in this one module — widgets are targeted by class,
objectName (e.g. ``primaryButton``, ``healthCard``) or the ``mutedLabel``
dynamic property. The only styling allowed elsewhere is *dynamic* (status
colors, badges, chat bubbles), and that must be built from the constants below;
raw hex literals never belong in tab code.

The palette matches the sibling llama-cag-n8n repo's identity: slate-navy
surfaces with an amber accent for primary actions and cache "heat", cyan for
informational/disk, green for healthy, red for errors.
"""

from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# --- palette ----------------------------------------------------------------

WINDOW_BG = "#0F172A"  # window background
SURFACE = "#1E293B"  # surfaces / panels
ELEVATED = "#253349"  # elevated / hover
BORDER = "#334155"  # borders
TEXT = "#E2E8F0"  # primary text
TEXT_MUTED = "#94A3B8"  # secondary text
ACCENT = "#F59E0B"  # amber: primary actions, cache heat, selected tab
ACCENT_HOVER = "#FBBF24"  # hover amber
CYAN = "#22D3EE"  # informational, disk-restore
GREEN = "#34D399"  # success / healthy
RED = "#F87171"  # errors / danger
DISABLED_TEXT = "#64748B"
DISABLED_BG = "#1A2436"

# Internal chrome details derived from the palette.
_BORDER_HOVER = "#3E4C63"
_DISABLED_BORDER = "#263145"


def tint(color: str, base: str = WINDOW_BG, alpha: float = 0.15) -> str:
    """Composite ``color`` at ``alpha`` over ``base`` and return solid hex.

    Qt's rich text engine and QSS handle solid colors most reliably, so tinted
    panels (14% amber bubbles, 15% chip backgrounds) are precomputed blends.
    """
    fg, bg = QColor(color), QColor(base)
    return QColor(
        round(fg.red() * alpha + bg.red() * (1 - alpha)),
        round(fg.green() * alpha + bg.green() * (1 - alpha)),
        round(fg.blue() * alpha + bg.blue() * (1 - alpha)),
    ).name()


def chip_style(color: str, base: str = SURFACE) -> str:
    """Stylesheet for a pill chip: colored text on a 15%-opacity colored bg."""
    return (
        f"color: {color}; background-color: {tint(color, base)}; "
        "border-radius: 10px; padding: 2px 10px; "
        "font-size: 11px; font-weight: 600;"
    )


# --- stylesheet -------------------------------------------------------------

_QSS_TEMPLATE = Template(
    """
QMainWindow, QDialog {
    background-color: $WINDOW_BG;
}

QLabel {
    background: transparent;
}
QLabel[mutedLabel="true"] {
    color: $TEXT_MUTED;
}

/* --- tabs ---------------------------------------------------------------- */
QTabWidget::pane {
    border: none;
    border-top: 1px solid $BORDER;
}
QTabBar {
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: $TEXT_MUTED;
    padding: 10px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}
QTabBar::tab:selected {
    color: $TEXT;
    border-bottom: 2px solid $ACCENT;
}
QTabBar::tab:hover:!selected {
    color: $TEXT;
}

/* --- buttons --------------------------------------------------------------*/
QPushButton {
    background-color: $SURFACE;
    color: $TEXT;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: $ELEVATED;
    border-color: $BORDER_HOVER;
}
QPushButton:pressed {
    background-color: $WINDOW_BG;
}
QPushButton:disabled {
    background-color: $DISABLED_BG;
    color: $DISABLED_TEXT;
    border-color: $DISABLED_BORDER;
}

QPushButton#primaryButton {
    background-color: $ACCENT;
    color: $WINDOW_BG;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background-color: $ACCENT_HOVER;
}
QPushButton#primaryButton:disabled {
    background-color: $DISABLED_BG;
    color: $DISABLED_TEXT;
}

QPushButton#startButton {
    background-color: $GREEN_TINT;
    color: $GREEN;
    border: 1px solid $GREEN_BORDER;
}
QPushButton#startButton:hover {
    background-color: $GREEN_TINT_HOVER;
}
QPushButton#stopButton {
    background-color: transparent;
    color: $RED;
    border: 1px solid $RED_BORDER;
}
QPushButton#stopButton:hover {
    background-color: $RED_TINT;
}
QPushButton#startButton:disabled, QPushButton#stopButton:disabled {
    background-color: $DISABLED_BG;
    color: $DISABLED_TEXT;
    border-color: $DISABLED_BORDER;
}

/* --- inputs ---------------------------------------------------------------*/
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: $SURFACE;
    color: $TEXT;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 5px 8px;
    selection-background-color: $ACCENT;
    selection-color: $WINDOW_BG;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {
    border-color: $ACCENT;
}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QComboBox:disabled {
    background-color: $DISABLED_BG;
    color: $DISABLED_TEXT;
    border-color: $DISABLED_BORDER;
}
QPlainTextEdit#chatInput {
    border-radius: 10px;
    padding: 8px 10px;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: $ELEVATED;
    color: $TEXT;
    border: 1px solid $BORDER;
    selection-background-color: $ACCENT;
    selection-color: $WINDOW_BG;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: transparent;
    border: none;
    width: 16px;
}

/* --- table ----------------------------------------------------------------*/
QTableWidget {
    background-color: $SURFACE;
    alternate-background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 10px;
    gridline-color: transparent;
}
QTableWidget::item {
    border-bottom: 1px solid $ELEVATED;
    padding: 4px 8px;
}
QTableWidget::item:selected {
    background-color: $SELECTION;
    color: $TEXT;
}
QHeaderView::section {
    background-color: $SURFACE;
    color: $TEXT_MUTED;
    border: none;
    border-bottom: 1px solid $BORDER;
    padding: 8px;
    font-weight: 600;
}
QTableCornerButton::section {
    background-color: $SURFACE;
    border: none;
}

/* --- group boxes ----------------------------------------------------------*/
QGroupBox {
    background-color: transparent;
    border: 1px solid $BORDER;
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: $ACCENT;
    font-weight: 700;
}

/* --- status bar -----------------------------------------------------------*/
QStatusBar {
    background-color: $SURFACE;
    border-top: 1px solid $BORDER;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    color: $TEXT_MUTED;
    padding: 0 8px;
}

/* --- chat transcript ------------------------------------------------------*/
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea#chatTranscript {
    background-color: $WINDOW_BG;
    border: 1px solid $BORDER;
    border-radius: 10px;
}
QWidget#chatTranscriptBody {
    background-color: $WINDOW_BG;
}

/* --- documents ------------------------------------------------------------*/
QLabel#dropHint {
    color: $TEXT_MUTED;
    border: 1px dashed $BORDER;
    border-radius: 8px;
    padding: 10px;
}

/* Centered muted hints shown over empty surfaces (transcript, documents). */
QLabel#emptyHint {
    color: $TEXT_MUTED;
    font-size: 13px;
    background: transparent;
}

/* --- stack tab ------------------------------------------------------------*/
QFrame#healthCard {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 10px;
}
QLabel#cardTitle {
    font-weight: 700;
    font-size: 14px;
    color: $TEXT;
}
QPlainTextEdit#stackLog {
    font-family: "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-size: 12px;
    background-color: $WINDOW_BG;
}
QLabel#maintenanceReport {
    font-family: "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-size: 12px;
    background-color: $WINDOW_BG;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 10px;
    color: $TEXT_MUTED;
}

/* --- welcome dialog -------------------------------------------------------*/
QLabel#heroTitle {
    font-size: 26px;
    font-weight: 800;
    color: $TEXT;
}
QLabel#heroTagline {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 2px;
    color: $ACCENT;
}

/* --- misc chrome ----------------------------------------------------------*/
QCheckBox {
    color: $TEXT;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $BORDER;
    border-radius: 4px;
    background-color: $SURFACE;
}
QCheckBox::indicator:checked {
    background-color: $ACCENT;
    border-color: $ACCENT;
}
QToolTip {
    background-color: $ELEVATED;
    color: $TEXT;
    border: 1px solid $BORDER;
    padding: 4px 8px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: $BORDER;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: $BORDER_HOVER;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $BORDER;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
"""
)


def build_qss() -> str:
    return _QSS_TEMPLATE.substitute(
        WINDOW_BG=WINDOW_BG,
        SURFACE=SURFACE,
        ELEVATED=ELEVATED,
        BORDER=BORDER,
        TEXT=TEXT,
        TEXT_MUTED=TEXT_MUTED,
        ACCENT=ACCENT,
        ACCENT_HOVER=ACCENT_HOVER,
        GREEN=GREEN,
        RED=RED,
        DISABLED_TEXT=DISABLED_TEXT,
        DISABLED_BG=DISABLED_BG,
        BORDER_HOVER=_BORDER_HOVER,
        DISABLED_BORDER=_DISABLED_BORDER,
        SELECTION=tint(ACCENT, SURFACE, 0.25),
        GREEN_TINT=tint(GREEN, SURFACE, 0.12),
        GREEN_TINT_HOVER=tint(GREEN, SURFACE, 0.2),
        GREEN_BORDER=tint(GREEN, SURFACE, 0.5),
        RED_TINT=tint(RED, SURFACE, 0.12),
        RED_BORDER=tint(RED, SURFACE, 0.5),
    )


def _build_palette() -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: WINDOW_BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: ELEVATED,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.BrightText: RED,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: WINDOW_BG,
        QPalette.ColorRole.Link: CYAN,
        QPalette.ColorRole.PlaceholderText: DISABLED_TEXT,
        QPalette.ColorRole.ToolTipBase: ELEVATED,
        QPalette.ColorRole.ToolTipText: TEXT,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(DISABLED_TEXT))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(DISABLED_TEXT))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(DISABLED_TEXT))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor(DISABLED_BG))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor(ELEVATED))
    palette.setColor(disabled, QPalette.ColorRole.HighlightedText, QColor(DISABLED_TEXT))
    return palette


def apply_theme(app: QApplication) -> None:
    """Fusion style (consistent cross-platform QSS rendering) + palette + QSS.

    Call once, right after the QApplication is constructed and before any
    window is built.
    """
    app.setStyle("Fusion")
    app.setPalette(_build_palette())
    # Segoe UI on Windows; Qt substitutes an equivalent sans elsewhere.
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(build_qss())
