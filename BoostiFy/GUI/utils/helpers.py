# helpers.py — вспомогательные функции для BoostiFy GUI

from BoostiFy.core.booster import SLOT_START_STAGGER_SEC, SteamBooster


def _range_average(cooldown_range):
    try:
        low, high = cooldown_range
        return (float(low) + float(high)) / 2
    except (TypeError, ValueError):
        return 0.0


def estimate_boost_seconds(count, batch, duration, launch_cd, finish_cd, slot_cd):
    """Предварительная оценка длительности буста — та же модель, что и во время работы.

    Слот — конвейер: одна задача живёт duration + кулдауны запуска/завершения/между.
    Раньше предварительная оценка считала только `ceil(games/slots) * duration` и
    игнорировала кулдауны, поэтому «Потребуется» до старта было в разы меньше, чем
    «Осталось» сразу после старта (booster.start_boost_sliding учитывает кулдауны).
    Держим формулу единой, чтобы число не прыгало при запуске.
    """
    count = max(0, int(count or 0))
    batch = max(1, int(batch or 1))
    if count == 0:
        return 0.0
    expected_task_sec = (
        max(0.0, float(duration or 0))
        + _range_average(launch_cd)
        + _range_average(finish_cd)
        + _range_average(slot_cd)
    )
    # Тот же расчёт, что и на первом тике буста, вместе с разгоном слотов: слот N
    # вступает через (N-1) шагов, и без этого числа расходились на ширину разгона.
    ramp = [index * SLOT_START_STAGGER_SEC for index in range(batch)]
    return SteamBooster._estimate_eta_seconds([], count, batch, expected_task_sec, 0.0, ramp)


def format_time_verbose(total_seconds):
    total_seconds = max(0, int(total_seconds or 0))
    weeks = total_seconds // 604800  # 7 * 24 * 3600
    days = (total_seconds % 604800) // 86400  # 24 * 3600
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    result = []
    if weeks > 0:
        result.append(f"{weeks} нед")
    if days > 0:
        result.append(f"{days} д")
    if hours > 0:
        result.append(f"{hours} ч")
    if minutes > 0:
        result.append(f"{minutes} мин")
    if seconds > 0 or not result:
        result.append(f"{seconds} сек")
    return ' '.join(result) 