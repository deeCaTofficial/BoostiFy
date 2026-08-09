"""BoostiFy desktop application by deeCaT / CLC corporation."""

__author__ = "deeCaT"
__company__ = "CLC corporation"
# Единственная версия, доступная в собранном exe: pyproject.toml и
# BoostiFy.version_info.txt внутрь сборки не попадают. С ней сверяется проверка
# обновлений, поэтому расхождение здесь не косметическое — устаревшее значение
# заставило бы программу вечно предлагать обновиться. Сходство всех трёх мест
# стережёт tests/test_version.py.
__version__ = "1.1.2"
