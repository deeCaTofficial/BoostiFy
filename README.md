<p align="center">
  <img src="./BoostiFy/Assets/BoostiFy.png" alt="BoostiFy" width="378"/>
</p>

<p align="center">
  <strong>Удобное управление Steam-активностью и достижениями.</strong>
  <br>
  <em>Современный интерфейс, параллельные сессии и изолированный runtime.</em>
</p>

<p align="center">
    <!-- Бейджи -->
    <a href="https://github.com/deeCaTofficial/BoostiFy/releases/latest"><img src="https://img.shields.io/github/v/release/deeCaTofficial/BoostiFy?display_name=tag&include_prereleases&label=release&color=blueviolet" alt="Latest Release"></a>
    <img src="https://img.shields.io/github/downloads/deeCaTofficial/BoostiFy/total?label=downloads&color=green" alt="Downloads">
    <a href="https://github.com/deeCaTofficial/BoostiFy/actions/workflows/ci.yml"><img src="https://github.com/deeCaTofficial/BoostiFy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <img src="https://img.shields.io/badge/python-3.14+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white" alt="PyQt6">
    <img src="https://img.shields.io/badge/.NET-4.8-512BD4?logo=dotnet&logoColor=white" alt=".NET Framework 4.8">
    <img src="https://img.shields.io/badge/Windows-0078D4?logo=windows&logoColor=white" alt="Windows">
    <a href="./LICENSE"><img src="https://img.shields.io/github/license/deeCaTofficial/BoostiFy" alt="License"></a>
</p>

---

> [!WARNING]
> Используйте BoostiFy только со своим Steam-аккаунтом. Автоматизация активности и
> изменение достижений могут иметь последствия для аккаунта или нарушать правила
> платформы. Вы используете эти возможности на свой риск.

## 🚀 Что нового в v1.1.0

Это обновление освежает техническую основу проекта и делает работу с
достижениями и статистикой заметно надёжнее и приятнее.

-   🐍 **Переход на Python 3.14:** проект переведён с Python 3.11 на 3.14 и
    обновлены используемые библиотеки — свежий рантайм, актуальные зависимости
    и задел на будущее.
-   🏆 **Исправлено получение достижений:** Steam хранит тип достижения то
    числом, то строкой (`"ACHIEVEMENTS"`) — из-за этого примерно у трети игр
    достижения не находились и в консоль писалось «нет достижений». Теперь
    распознаются оба формата, и разблокировка работает стабильно.
-   📊 **Переработана вкладка «Статистика»:** приведена к единому
    минималистичному стилю с остальными вкладками — крупные плитки-показатели,
    больше воздуха, меньше визуального шума.
-   🧹 **Мелкие правки и улучшения:** исправлена обрезанная надпись на кнопке
    подтверждения, устранён сбой записи причины ошибки в чёрный список и ряд
    косметических доработок интерфейса.

*Версия 1.1.0 не меняет привычный сценарий работы — она делает его надёжнее,
аккуратнее и современнее под капотом.*

## ✨ Почему BoostiFy

BoostiFy объединяет простой PyQt6-интерфейс и отдельный C# runtime для работы со
Steam. Интерфейс остаётся отзывчивым, тяжёлые операции выполняются в фоне, а
каждая игра обрабатывается собственным изолированным worker-процессом.

| Возможность | Что получает пользователь |
| --- | --- |
| **Параллельные сессии** | Одновременная обработка нескольких игр с настраиваемым количеством слотов. |
| **Умная очередь** | Скользящий запуск, задержки между задачами и ETA на основе реального расписания слотов. |
| **Проверка владения** | AppID проверяется через запущенный Steam Client перед добавлением игры. |
| **Достижения** | Опциональная разблокировка с отдельным предупреждением перед запуском. |
| **Надёжное завершение** | Windows Job Object останавливает дочерние workers даже при аварийном закрытии GUI. |
| **Безопасное хранение** | JSON записывается атомарно, ввод нормализуется, пользовательские данные находятся вне каталога программы. |

## 🚀 Ключевые возможности

-   🎮 **Добавление игр** по AppID или точному названию, с массовым импортом всей библиотеки аккаунта.
-   ⚡ **До 60 параллельных слотов** с отдельными задержками запуска, завершения и между задачами.
-   🏆 **Опциональная работа с достижениями** с явным подтверждением перед изменением данных Steam.
-   📈 **Живой прогресс и статистика:** расчёт оставшегося времени, распределение статусов и история сессий.
-   🔁 **Циклический режим** и автоматическая очистка таблицы.
-   🔎 **Фильтрация, сортировка** и быстрое управление таблицей игр.
-   🛡️ **Нормализация конфигурации,** AppID и повреждённых данных, а также ротируемые логи для диагностики.

## 🛠️ Установка и запуск

Для работы не нужно устанавливать Python, .NET SDK или собирать проект вручную.

1.  Перейдите на страницу **[последнего релиза](https://github.com/deeCaTofficial/BoostiFy/releases/latest)**.
2.  Скачайте `BoostiFy.exe` из раздела **Assets**.
3.  Убедитесь, что Steam запущен и выполнен вход в аккаунт.
4.  Запустите `BoostiFy.exe`.

<p align="center">
  <a href="https://github.com/deeCaTofficial/BoostiFy/releases/latest">
    <img src="https://img.shields.io/badge/Скачать-BoostiFy.exe-2F80ED?style=for-the-badge&logo=windows&logoColor=white" alt="Скачать BoostiFy.exe">
  </a>
</p>

Все настройки, выбранные игры и статистика сохраняются между обновлениями в
`%LOCALAPPDATA%\BoostiFy`.

## 🤝 Участие в разработке

Сообщения об ошибках, идеи и pull request приветствуются. Перед отправкой изменений
пожалуйста, запустите unit-тесты, Ruff, smoke-тест и функциональный GUI-прогон.

Если ошибка связана со Steam runtime, приложите версии Windows и Steam, AppID,
последние строки лога и укажите, воспроизводится ли проблема в `--self-test`.

## 🔧 Технический обзор

BoostiFy построен на **Python 3.14** и **PyQt6**, а вся работа со Steam вынесена
в отдельный **C# runtime на .NET Framework 4.8**. GUI и runtime общаются через
изолированные worker-процессы: падение одной игры не влияет на интерфейс, а
Windows Job Object гарантирует остановку всех дочерних процессов вместе с GUI.

```bash
# Запуск из исходников
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
python BoostiFy/runtime/build.py        # собрать изолированный C# runtime
.venv\Scripts\python main.py

# Тесты и проверки качества
.venv\Scripts\pytest
.venv\Scripts\ruff check .
.venv\Scripts\python scripts/smoke_test.py --require-runtime
.venv\Scripts\python scripts/functional_qa.py

# Сборка исполняемого файла
.venv\Scripts\python scripts/package.py
```

## 📄 Лицензия

BoostiFy распространяется под лицензией **MIT**. Вы можете использовать, изменять и
распространять проект при условии сохранения уведомления об авторских правах и
текста лицензии. Подробности приведены в файле [LICENSE](./LICENSE).

---

<p align="center">
  <em>Разработано с ❤️ под маркой <strong>CLC corporation</strong><br>
  <a href="https://github.com/deeCaTofficial">@deeCaT</a></em>
</p>
