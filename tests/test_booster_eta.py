from BoostiFy.core.booster import SteamBooster


# Задача слота: launch_cd -> игра (duration + finish_cd) -> slot_cd.
# 12 часов при дефолтных кулдаунах (20 + 20 + 75).
TASK = 43200 + 20 + 20 + 75


def eta(slot_starts, queued, num_slots, now, task_seconds=TASK):
    return SteamBooster._estimate_eta_seconds(
        slot_starts, queued, num_slots, task_seconds, now
    )


def test_partial_wave_costs_a_full_wave():
    """18 игр в 20 слотов — это одна волна на все 12 часов, а не 0.9 волны.

    Прежняя формула (len(appids) / num_slots) * task давала 0.9 * 12ч = 10ч50м
    и линейно вычитала время: на 15-й минуте показывала 10ч34м вместо 11ч47м.
    """
    now = 1000.0
    starts = [now] * 18
    assert eta(starts, queued=0, num_slots=20, now=now) == TASK

    # Через 15 минут остаток честно уменьшается ровно на 15 минут.
    assert eta(starts, queued=0, num_slots=20, now=now + 900) == TASK - 900


def test_eta_reaches_zero_when_the_last_game_ends():
    now = 1000.0
    starts = [now] * 18
    assert eta(starts, queued=0, num_slots=20, now=now + TASK) == 0.0
    # И не уходит в минус, если игра пережила расчётный срок.
    assert eta(starts, queued=0, num_slots=20, now=now + TASK + 600) == 0.0


def test_queue_is_scheduled_onto_the_earliest_free_slot():
    now = 1000.0
    # 2 слота заняты, 3 игры ждут: 1 уйдёт в свободный слот (сразу),
    # 2 других — в слоты, которые освободятся через TASK.
    starts = [now, now]
    assert eta(starts, queued=3, num_slots=3, now=now) == 2 * TASK


def test_full_waves_stack_without_free_slots():
    now = 1000.0
    # 2 слота заняты, ещё 2 игры в очереди -> вторая волна поверх первой.
    assert eta([now, now], queued=2, num_slots=2, now=now) == 2 * TASK
    # 5 игр на 2 слота: волны = ceil(5/2) = 3.
    assert eta([now, now], queued=3, num_slots=2, now=now) == 3 * TASK


def test_idle_slots_and_empty_session_report_zero():
    now = 1000.0
    assert eta([], queued=0, num_slots=20, now=now) == 0.0
    # Слоты есть, работы нет — ETA ноль, а не «время одной игры».
    assert eta([], queued=0, num_slots=1, now=now) == 0.0


def test_running_slot_keeps_its_own_remainder():
    now = 1000.0
    # Слот стартовал 2 часа назад — остаток именно его, а не полный TASK.
    started_two_hours_ago = now - 7200
    assert eta([started_two_hours_ago], queued=0, num_slots=1, now=now) == TASK - 7200


def test_eta_uses_the_latest_finishing_slot():
    now = 1000.0
    # Слоты стартовали в разное время: ETA — по самому позднему.
    starts = [now - 7200, now - 60, now]
    assert eta(starts, queued=0, num_slots=3, now=now) == TASK
