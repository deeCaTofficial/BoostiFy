import struct
from pathlib import Path
from collections import defaultdict

# --- НАСТРОЙКА: Список папок и файлов, которые нужно полностью игнорировать ---
# Добавьте сюда любой "мусор", который вы не хотите видеть в отчете.
EXCLUDE_LIST = {
    '__pycache__', 
    '.git', 
    '.vs', 
    'bin', 
    'obj'
}

def find_project_root() -> Path:
    start = Path(__file__).resolve()
    for path in (start.parent, *start.parents):
        if (path / 'BoostiFy' / 'runtime' / 'Boostify.Runtime.sln').exists():
            return path
        if (path / 'Boostify.Runtime.sln').exists():
            return path
    return start.parent

def get_binary_architecture(file_path: Path) -> str:
    """Читает заголовок файла и определяет его архитектуру (x86 или x64)."""
    try:
        with open(file_path, 'rb') as f:
            if f.read(2) != b'MZ':
                return None  # Не является исполняемым файлом Windows
            
            f.seek(0x3c)
            pe_header_offset = struct.unpack('<I', f.read(4))[0]
            f.seek(pe_header_offset)
            if f.read(4) != b'PE\0\0':
                return "PE-заголовок не найден"

            magic = struct.unpack('<H', f.read(22)[-2:])[0]
            
            if magic == 0x10b:
                return "x86"
            elif magic == 0x20b:
                return "x64"
            else:
                return "Неизвестно"
    except (IOError, struct.error):
        return "Ошибка чтения"

def get_file_annotation(path: Path) -> str:
    """Создает аннотацию для файла на основе его типа и содержимого."""
    suffix = path.suffix.lower()
    
    if suffix == '.sln':
        return "[sln] Файл Решения"
    if suffix == '.csproj':
        return "[csproj] Файл Проекта"
    
    if suffix in ['.exe', '.dll']:
        arch = get_binary_architecture(path)
        if arch:
            return f"[bin] Бинарный файл [{arch}]"
            
    if suffix == '.py':
        return "[py] Скрипт Python"
    if suffix == '.ps1':
        return "[ps1] Скрипт PowerShell"
    if suffix == '.cs':
        return "[cs] Файл C#"
        
    return ""

def print_tree(root_path: Path, prefix: str = "", findings: defaultdict = None):
    """Рекурсивно обходит директории и печатает их содержимое в виде дерева."""
    
    # Получаем содержимое папки, исключая мусор, и сортируем (папки первыми)
    try:
        entries = sorted(
            [p for p in root_path.iterdir() if p.name not in EXCLUDE_LIST],
            key=lambda p: (p.is_file(), p.name.lower())
        )
    except PermissionError:
        print(f"{prefix}`-- [denied] Отказано в доступе")
        return

    for i, entry in enumerate(entries):
        # Определяем ASCII-соединитель для совместимости с Windows-консолью.
        is_last = (i == len(entries) - 1)
        connector = "`-- " if is_last else "|-- "
        
        annotation = get_file_annotation(entry)
        if annotation:
            print(f"{prefix}{connector}{entry.name}   ({annotation})")
            if "Файл Решения" in annotation:
                findings['solutions'].append(entry)
            if "Файл Проекта" in annotation:
                findings['projects'].append(entry)
        else:
             print(f"{prefix}{connector}{entry.name}")

        # Рекурсивный вызов для подпапок
        if entry.is_dir():
            new_prefix = prefix + ("    " if is_last else "|   ")
            print_tree(entry, new_prefix, findings)


def main():
    """Главная функция для запуска анализа."""
    # Корень проекта - это папка, где лежит этот скрипт
    project_root = find_project_root()
    print(f"[TREE] Анализ полной структуры проекта в: {project_root}\n")
    print(f"{project_root.name}/")

    # Словарь для сбора ключевых находок
    findings = defaultdict(list)
    
    # Запускаем отрисовку дерева
    print_tree(project_root, findings=findings)
    
    # --- Вывод итогового резюме ---
    print("\n\n--- ИТОГОВОЕ РЕЗЮМЕ ---")
    if findings['solutions']:
        print(f"\n[OK] Найдено файлов Решения (.sln): {len(findings['solutions'])}")
        for path in findings['solutions']:
            print(f"  -> {path.relative_to(project_root)}")
    else:
        print("\n[WARN] Файл .sln не найден.")

    if findings['projects']:
        print(f"\n[OK] Найдено файлов Проектов (.csproj): {len(findings['projects'])}")
        for path in findings['projects']:
            print(f"  -> {path.relative_to(project_root)}")
    else:
         print("\n[WARN] Файлы .csproj не найдены!")
         
    print("\nАнализ завершен.")


if __name__ == "__main__":
    main()
