"""Application entry point: build the QApplication, gate the welcome dialog, run.

Console script `llamacag-ui` calls main(). Kept deliberately thin — everything
of substance lives in the modules it wires together.
"""

import sys

from PySide6.QtWidgets import QApplication

from .config import AppConfig
from .ui.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    # Same org/app as v1, so QSettings carries over harmlessly.
    app.setOrganizationName("LlamaCag")
    app.setApplicationName("LlamaCagUI")
    app.setApplicationDisplayName("LlamaCag UI")
    apply_theme(app)

    config = AppConfig()

    # Imported lazily so a headless import of this module (or a config-only
    # test) never has to construct the whole widget tree.
    from .ui.main_window import MainWindow

    window = MainWindow(config)
    window.show()

    if config.show_welcome:
        from .ui.welcome_dialog import WelcomeDialog

        WelcomeDialog(config, parent=window).exec()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
