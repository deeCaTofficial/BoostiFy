# helpers.py — вспомогательные функции для BoostiFy GUI

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