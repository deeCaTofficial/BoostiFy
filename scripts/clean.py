import shutil
from pathlib import Path

def find_project_root() -> Path:
    start = Path(__file__).resolve()
    for path in (start.parent, *start.parents):
        if (path / 'BoostiFy' / 'runtime' / 'Boostify.Runtime.sln').exists():
            return path
    return start.parent

def clean_build_artifacts(root_path: Path):
    """
    "Силовая" очистка: рекурсивно находит и удаляет все папки 'bin' и 'obj'.
    Это гарантирует полное удаление всех результатов предыдущих сборок.
    """
    print("\n--- Step 1: Force-cleaning all .NET build artifacts (all bin/obj folders) ---")
    
    folders_to_delete = ['bin', 'obj']
    
    # Рекурсивно ищем все папки с нужными именами
    for folder_name in folders_to_delete:
        for path in root_path.rglob(folder_name):
            # Проверяем, что это действительно папка, а не файл с таким же именем
            if path.is_dir():
                try:
                    shutil.rmtree(path)
                    print(f"Deleted folder: {path.relative_to(root_path)}")
                except OSError as e:
                    print(f"[ERROR] Error deleting folder {path}: {e}. It might be in use.")

def clean_specific_files(root_path: Path):
    """
    Удаляет специфические временные файлы и папки, не относящиеся к .NET.
    """
    print("\n--- Step 2: Cleaning other temporary files and folders ---")

    # 1. Удаление папок __pycache__
    for path in root_path.rglob('__pycache__'):
        if path.is_dir():
            try:
                shutil.rmtree(path)
                print(f"Deleted folder: {path.relative_to(root_path)}")
            except OSError as e:
                print(f"Error deleting folder {path}: {e}")

    # 2. Удаление конкретных файлов
    files_to_delete = ['gui_debug_log.txt']
    for filename in files_to_delete:
        for path in root_path.rglob(filename):
            if path.is_file():
                try:
                    path.unlink()
                    print(f"Deleted file: {path.relative_to(root_path)}")
                except OSError as e:
                    print(f"Error deleting file {path}: {e}")

def main():
    """Главная функция для запуска всего процесса очистки."""
    # Определяем корень проекта как папку, где лежит сам скрипт
    project_root = find_project_root()
    print(f"--- Starting full cleanup in '{project_root.name}' ---")
    
    # Очищаем .NET-артефакты только внутри runtime-модуля.
    runtime_root = project_root / 'BoostiFy' / 'runtime'
    if runtime_root.is_dir():
        clean_build_artifacts(runtime_root)
    else:
        print(f"[WARN] Runtime folder not found at {runtime_root}. Skipping .NET cleanup.")
        
    # 2. Запускаем очистку остальных артефактов по всему проекту
    clean_specific_files(project_root)
    
    print("\n--- Cleanup finished! ---")

if __name__ == "__main__":
    main()
