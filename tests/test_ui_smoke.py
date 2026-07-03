"""Offscreen UI smoke tests (pytest-qt).

They exercise the signal wiring end to end against the in-memory FakeCagApi:
window construction, the documents table populating from a manual poll, a full
chat send round-trip rendering an answer bubble with a cache badge, and the
degraded-health path disabling send. Workers run on QThreadPool, so we wait on
observable state with ``qtbot.waitUntil``.
"""

from __future__ import annotations

from llamacag_ui.ui.chat_tab import LATEST_LABEL


def _wait(qtbot, predicate, timeout=3000):
    qtbot.waitUntil(predicate, timeout=timeout)


# --- construction ----------------------------------------------------------


def test_window_has_four_tabs(main_window):
    labels = [main_window.tabs.tabText(i) for i in range(main_window.tabs.count())]
    assert labels == ["Chat", "Documents", "Stack", "Settings"]


def test_status_bar_dots_exist(main_window):
    assert main_window.api_dot is not None
    assert main_window.llama_dot is not None
    assert main_window.db_dot is not None


# --- documents table -------------------------------------------------------


def test_documents_table_populates_from_fake(main_window, fake_api, qtbot):
    fake_api.add_document("alpha.txt")
    fake_api.add_document("beta.md")
    main_window.documents_tab.refresh()

    _wait(qtbot, lambda: main_window.documents_tab.table.rowCount() == 2)
    table = main_window.documents_tab.table
    names = {table.item(r, 1).text() for r in range(table.rowCount())}
    assert names == {"alpha.txt", "beta.md"}


def test_documents_feed_chat_picker(main_window, fake_api, qtbot):
    fake_api.add_document("alpha.txt")
    fake_api.add_document("draft.md", status="pending", n_tokens=None)
    main_window.documents_tab.refresh()

    _wait(qtbot, lambda: main_window.documents_tab.table.rowCount() == 2)
    combo = main_window.chat_tab.document_combo
    # "(latest)" + only the cached document (pending one is excluded).
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels[0] == LATEST_LABEL
    assert any("alpha.txt" in label for label in labels)
    assert not any("draft.md" in label for label in labels)


# --- health gating ---------------------------------------------------------


def test_healthy_poll_enables_send(main_window, fake_api, qtbot):
    # Wait on the health result actually landing (send starts enabled by
    # default, so gating the wait on the button would race the worker).
    main_window.poll_health_now()
    _wait(qtbot, lambda: main_window.status_text.text() == "Stack status: ok")
    assert main_window.chat_tab.send_button.isEnabled()


def test_degraded_health_disables_send(main_window, fake_api, qtbot):
    fake_api.llama_healthy = False
    main_window.poll_health_now()
    _wait(
        qtbot,
        lambda: "unavailable" in main_window.chat_tab.status_label.text().lower(),
    )
    assert main_window.chat_tab.send_button.isEnabled() is False


def test_unreachable_marks_api_dot_down(main_window, fake_api, qtbot):
    fake_api.reachable = False
    main_window.poll_health_now()
    _wait(qtbot, lambda: "unreachable" in main_window.status_text.text().lower())
    assert main_window.chat_tab.send_button.isEnabled() is False


# --- chat round-trip -------------------------------------------------------


def test_chat_send_renders_answer_with_badge(main_window, fake_api, qtbot):
    fake_api.add_document("facts.txt")
    fake_api.cache_source = "memory"

    # Ensure send is enabled first.
    main_window.poll_health_now()
    _wait(qtbot, lambda: main_window.chat_tab.send_button.isEnabled())

    chat = main_window.chat_tab
    chat.input.setPlainText("What is the capital?")
    chat.send()

    _wait(qtbot, lambda: "Fredville" in chat.transcript.toPlainText())
    text = chat.transcript.toPlainText()
    assert "What is the capital?" in text  # user bubble
    assert "The capital is Fredville." in text  # answer bubble
    assert "memory" in text  # cache badge
    assert "480 cached" in text or "480" in text  # token economics footer
    # History captured for the next turn (user + assistant).
    assert len(chat._history) == 2


def test_chat_error_becomes_bubble_and_preserves_history(main_window, fake_api, qtbot):
    fake_api.add_document("facts.txt")
    main_window.poll_health_now()
    _wait(qtbot, lambda: main_window.chat_tab.send_button.isEnabled())

    chat = main_window.chat_tab
    # First successful turn.
    chat.input.setPlainText("First question?")
    chat.send()
    _wait(qtbot, lambda: len(chat._history) == 2)

    # Now break llama so the next query 502s.
    fake_api.llama_healthy = False
    chat.set_send_enabled(True)  # simulate still-enabled between polls
    chat.input.setPlainText("Second question?")
    chat.send()

    _wait(qtbot, lambda: "Error" in chat.transcript.toPlainText())
    # The failed turn did not append to history; the first turn is preserved.
    assert len(chat._history) == 2


def test_clear_conversation_resets(main_window, fake_api, qtbot):
    fake_api.add_document("facts.txt")
    main_window.poll_health_now()
    _wait(qtbot, lambda: main_window.chat_tab.send_button.isEnabled())

    chat = main_window.chat_tab
    chat.input.setPlainText("Q?")
    chat.send()
    _wait(qtbot, lambda: len(chat._history) == 2)

    chat.clear_conversation()
    assert chat._history == []
    assert chat.transcript.toPlainText().strip() == ""


# --- stack tab -------------------------------------------------------------


def test_stack_cards_update_from_health(main_window, fake_api, qtbot):
    fake_api.add_document("facts.txt")
    fake_api.hot_documents = {"0": 1}
    main_window.poll_health_now()
    _wait(qtbot, lambda: "1 of" in main_window.stack_tab.hot_label.text())
    assert "document #1" in main_window.stack_tab.hot_label.text()


def test_stack_controls_disabled_without_stack_dir(main_window):
    # No stack dir configured -> controls disabled with an explanation.
    assert main_window.stack_tab.start_button.isEnabled() is False
    assert main_window.stack_tab.control_hint.text() != ""


def test_maintenance_renders_report(main_window, fake_api, qtbot):
    fake_api.add_document("keep.txt")
    main_window.stack_tab._run_maintenance()
    _wait(qtbot, lambda: "Cache files on disk" in main_window.stack_tab.maintenance_report.text())
    assert "Documents" in main_window.stack_tab.maintenance_report.text()


# --- settings tab ----------------------------------------------------------


def test_settings_apply_repoints_client(main_window, fake_api, qtbot):
    settings = main_window.settings_tab
    settings.api_url_edit.setText("http://newhost:8000")
    original_client = main_window._client
    settings.apply()
    # A fresh client object was created via the factory.
    assert main_window._client is not original_client
    assert main_window._config.api_url == "http://newhost:8000"
