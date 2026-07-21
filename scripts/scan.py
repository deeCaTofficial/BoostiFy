import os
from pathlib import Path

def find_project_root(start: Path) -> Path | None:
    for path in (start, *start.parents):
        if (path / 'BoostiFy' / 'runtime' / 'Boostify.Runtime.sln').exists():
            return path / 'BoostiFy' / 'runtime'
        if (path / 'Boostify.Runtime.sln').exists():
            return path
    return None

def find_project_root_and_files():
    """
    Находит корень проекта (папку с .sln файлом), поднимаясь вверх от текущей директории.
    Затем ищет все .sln и .exe файлы внутри найденного корня.
    """
    # Начинаем поиск с директории, где лежит сам скрипт
    current_path = Path(__file__).resolve().parent
    root_path = None

    print(f"[INFO] Начальная точка поиска: {current_path}")
    
    root_path = find_project_root(current_path)
    if root_path:
        print(f"[OK] Корень C# проекта найден: {root_path}\n")
    
    # Если мы дошли до корня диска и ничего не нашли
    if not root_path:
        print("[ERROR] Не удалось найти .sln файл.")
        print("   Убедитесь, что вы скачали проект целиком и что он содержит .sln файл.")
        return

    # Теперь, когда мы знаем корень проекта, ищем файлы внутри него
    sln_files = []
    exe_files = []

    print(f"[INFO] Поиск файлов внутри {root_path}...")
    for root, dirs, files in os.walk(root_path):
        for file_name in files:
            lower_name = file_name.lower()
            if lower_name.endswith('.sln'):
                sln_files.append(Path(root) / file_name)
            elif lower_name.endswith('.exe'):
                exe_files.append(Path(root) / file_name)

    # --- Вывод результатов ---
    print("\n--- Результаты поиска ---")
    if sln_files:
        print("\n[OK] Найденные файлы Решения (.sln):")
        for path in sln_files:
            print(f"  -> {path.relative_to(root_path)}")
        print("\n   Runtime собирается скриптом BoostiFy/runtime/build.py")
    else:
        # Эта ветка почти невозможна, если мы нашли root_path, но добавлена для полноты
        print("\n[WARN] Файлы Решения (.sln) не найдены.")

    if exe_files:
        print("\n[OK] Найденные исполняемые файлы (.exe) (обычно находятся в папках bin/ или obj/):")
        for path in exe_files:
            print(f"  -> {path.relative_to(root_path)}")
    else:
        print("\n[INFO] Исполняемые файлы (.exe) не найдены. Скорее всего, проект еще ни разу не был успешно собран.")

if __name__ == "__main__":
    find_project_root_and_files()
