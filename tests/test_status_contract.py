"""Контракт между booster, GUI и статистикой.

SteamBooster шлёт протокольные коды ("done", "error: ...", "skipped: black list"),
GUI переводит их в русские подписи через _display_status, а статистика
классифицирует игры по префиксам этих подписей. Связь держится на совпадении
литералов в трёх модулях, и functional_qa её не проверяет: тамошний фейковый
booster отдаёт сразу "Готово", минуя слой перевода.

Из-за этого переименование в _display_status ('done': 'Завершено') прошло бы все
прогоны зелёными, а в проде успешные игры молча перестали бы попадать в
статистику. Тест ниже закрывает именно этот разрыв — он идёт от кода протокола,
а не от готовой подписи.
"""

import pytest

from BoostiFy.GUI.core.statistics_storage import classify_game_statuses


@pytest.fixture(scope="module")
def display_status():
    """_display_status — staticmethod на виджете, поэтому нужен QApplication."""
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from BoostiFy.GUI.screens.main_screen import MainScreenWidget

    return MainScreenWidget._display_status


def classify_one(status):
    """Возвращает корзину статистики для одной игры."""
    counts = classify_game_statuses([{"status": status}])
    return next((name for name, value in counts.items() if value), None)


@pytest.mark.parametrize(
    ("protocol_code", "expected_bucket"),
    [
        ("done", "successful"),
        ("error: exit code 1", "failed"),
        ("error: Steam не ответил на проверку владения.", "failed"),
        ("skipped: black list", "skipped"),
    ],
)
def test_protocol_code_survives_translation_into_statistics(
    display_status, protocol_code, expected_bucket
):
    assert classify_one(display_status(protocol_code)) == expected_bucket


def test_finalize_fallback_statuses_are_classified():
    """finalize_session_statuses пишет эти подписи напрямую, минуя _display_status."""
    assert classify_one("Не выполнено") == "failed"
    assert classify_one("Остановлено") == "other"


def test_transient_statuses_never_count_as_finished(display_status):
    """Пока игра в работе, она не должна попадать в успешные/провальные."""
    for code in ("started", "В очереди", "Ожидание"):
        assert classify_one(display_status(code)) == "other"


def test_unknown_code_is_not_silently_counted_as_success(display_status):
    """Незнакомый код обязан осесть в other, а не изобразить успех."""
    assert classify_one(display_status("some-new-code")) == "other"
