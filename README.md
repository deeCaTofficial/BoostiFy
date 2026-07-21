<p align="center">
  <img src="./BoostiFy/Assets/BoostiFy.png" alt="BoostiFy" width="430">
</p>

<p align="center">
  <strong>Удобное управление Steam-активностью и достижениями.</strong>
  <br>
  <em>Современный интерфейс, параллельные сессии и изолированный runtime.</em>
</p>

<p align="center">
  <a href="https://github.com/deeCaTofficial/BoostiFy/actions/workflows/ci.yml"><img src="https://github.com/deeCaTofficial/BoostiFy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/deeCaTofficial/BoostiFy/releases"><img src="https://img.shields.io/github/downloads/deeCaTofficial/BoostiFy/total?label=downloads&color=brightgreen" alt="Downloads"></a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows" alt="Windows">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white" alt="PyQt6">
  <img src="https://img.shields.io/badge/runtime-.NET%20Framework%204.8-512BD4?logo=dotnet&logoColor=white" alt=".NET Framework 4.8">
  <img src="https://img.shields.io/badge/code%20style-Ruff-D7FF64?logo=ruff&logoColor=black" alt="Code style: Ruff">
</p>

---

> [!WARNING]
> Используйте BoostiFy только со своим Steam-аккаунтом. Автоматизация активности и
> изменение достижений могут иметь последствия для аккаунта или нарушать правила
> платформы. Вы используете эти возможности на свой риск.

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

## 🚀 Возможности

- 🎮 Добавление игры по AppID или точному названию.
- 📚 Массовый импорт принадлежащих аккаунту игр.
- ⚡ До 60 параллельных слотов с отдельными задержками запуска и завершения.
- 🏆 Опциональная работа с достижениями.
- 🔎 Фильтрация, сортировка и быстрое управление таблицей.
- 📈 Живой прогресс, расчёт оставшегося времени и история сессий.
- 🔁 Циклический режим и автоматическая очистка таблицы.
- 🧩 Отдельные console и windowed workers для диагностики и фоновой работы.
- 🛡️ Нормализация конфигурации, AppID и повреждённых данных.
- 📝 Ротируемые логи для диагностики проблем.

## 🛠️ Установка и запуск

Для работы не нужно устанавливать Python, .NET SDK или собирать проект вручную.

1. Перейдите на страницу **[последнего релиза](https://github.com/deeCaTofficial/BoostiFy/releases/latest)**.
2. Скачайте `BoostiFy.exe` из раздела **Assets**.
3. Убедитесь, что Steam запущен и выполнен вход в аккаунт.
4. Запустите `BoostiFy.exe`.

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

---

<p align="center">
  <em>Разработано с ❤️ под маркой <strong>CLC corporation</strong><br>
  <a href="https://github.com/deeCaTofficial">@deeCaT</a></em>
</p>
