import io
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from BoostiFy import __version__
from BoostiFy.core import app_paths, updates

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# --------------------------- разбор и сравнение версий ---------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("1.1.2", (1, 1, 2)),
        ("v1.1.2", (1, 1, 2)),
        ("V1.1.2", None),  # регистр тега мы не выдумываем: GitHub пишет 'v'
        ("1.2", (1, 2)),
        ("v2.0.0-beta1", (2, 0, 0)),
        ("", None),
        ("latest", None),
        (None, None),
    ],
)
def test_parse_version(text, expected):
    assert updates.parse_version(text) == expected


@pytest.mark.parametrize(
    "candidate,current,expected",
    [
        ("v1.1.3", "1.1.2", True),
        ("v1.2.0", "1.1.9", True),
        ("v2.0.0", "1.9.9", True),
        ("v1.1.2", "1.1.2", False),
        ("v1.1.1", "1.1.2", False),
        ("v1.10.0", "1.9.0", True),  # числами, а не строками: '10' > '9'
        ("v1.2", "1.2.0", False),  # разная длина — та же версия
        ("v1.2.0", "1.2", False),
        ("v1.2.1", "1.2", True),
        ("мусор", "1.1.2", False),
        ("v1.1.3", "", False),
    ],
)
def test_is_newer(candidate, current, expected):
    assert updates.is_newer(candidate, current) is expected


# ------------------------------- ответ GitHub -------------------------------

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _patch_api(monkeypatch, payload=None, error=None):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        if error is not None:
            raise error
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


def test_fetch_latest_release_reads_tag_and_url(monkeypatch):
    captured = _patch_api(
        monkeypatch,
        {
            "tag_name": "v1.1.3",
            "html_url": f"https://github.com/{updates.REPOSITORY}/releases/tag/v1.1.3",
        },
    )
    assert updates.fetch_latest_release() == (
        "v1.1.3",
        f"https://github.com/{updates.REPOSITORY}/releases/tag/v1.1.3",
    )
    assert captured["url"] == updates.LATEST_RELEASE_API
    # Без User-Agent GitHub отвечает 403 — заголовок обязателен.
    assert any(name.lower() == "user-agent" for name in captured["headers"])
    assert captured["timeout"] == updates.REQUEST_TIMEOUT


def test_foreign_html_url_is_replaced_with_own_releases_page(monkeypatch):
    """html_url приходит извне: открывать в браузере что попало нельзя."""
    _patch_api(
        monkeypatch,
        {"tag_name": "v1.1.3", "html_url": "https://evil.example/phishing"},
    )
    assert updates.fetch_latest_release() == ("v1.1.3", updates.RELEASES_PAGE)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tag_name": ""},
        {"tag_name": "не версия"},
        {"tag_name": None},
        [],
        "строка вместо объекта",
    ],
)
def test_unusable_payload_yields_none(monkeypatch, payload):
    _patch_api(monkeypatch, payload)
    assert updates.fetch_latest_release() is None


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("нет сети"),
        urllib.error.HTTPError("url", 403, "rate limit", {}, None),
        TimeoutError("истекло время ожидания"),
        OSError("сокет закрыт"),
    ],
)
def test_network_failures_are_silent(monkeypatch, error):
    _patch_api(monkeypatch, error=error)
    assert updates.fetch_latest_release() is None
    assert updates.check_for_update(current_version="1.1.2") is None


def test_broken_json_is_silent(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(b"<html>503 Service Unavailable</html>")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert updates.fetch_latest_release() is None


# ------------------------------ решение показывать ------------------------------

@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Каталог данных на время теста.

    Без подмены проверка писала бы update_state.json в настоящий
    %LOCALAPPDATA%\\BoostiFy и трогала данные пользователя.
    """
    monkeypatch.setattr(app_paths, "DATA_DIR", tmp_path)
    return tmp_path


def test_update_reported_when_github_is_ahead(monkeypatch, isolated_data_dir):
    _patch_api(monkeypatch, {"tag_name": "v1.1.3", "html_url": ""})
    update = updates.check_for_update(current_version="1.1.2")
    assert update is not None
    assert update.version == "v1.1.3"
    assert update.current == "1.1.2"
    assert update.url == updates.RELEASES_PAGE


def test_no_update_when_versions_match(monkeypatch, isolated_data_dir):
    _patch_api(monkeypatch, {"tag_name": "v1.1.2", "html_url": ""})
    assert updates.check_for_update(current_version="1.1.2") is None


def test_no_update_when_local_build_is_ahead(monkeypatch, isolated_data_dir):
    """Сборка из исходников новее последнего релиза — не повод предлагать откат."""
    _patch_api(monkeypatch, {"tag_name": "v1.1.2", "html_url": ""})
    assert updates.check_for_update(current_version="1.2.0") is None


def test_skipped_version_is_not_offered_again(monkeypatch, isolated_data_dir):
    _patch_api(monkeypatch, {"tag_name": "v1.1.3", "html_url": ""})
    assert updates.check_for_update(current_version="1.1.2") is not None
    assert updates.remember_skipped_version("v1.1.3") is True
    assert updates.check_for_update(current_version="1.1.2") is None


def test_skip_applies_only_to_that_version(monkeypatch, isolated_data_dir):
    updates.remember_skipped_version("v1.1.3")
    _patch_api(monkeypatch, {"tag_name": "v1.1.4", "html_url": ""})
    assert updates.check_for_update(current_version="1.1.2") is not None


def test_corrupted_state_file_does_not_break_check(isolated_data_dir):
    (isolated_data_dir / "update_state.json").write_text("{не json", encoding="utf-8")
    assert updates.load_skipped_version() == ""


def test_missing_state_file_is_not_an_error(isolated_data_dir):
    assert updates.load_skipped_version() == ""


# ------------------------------ версия проекта ------------------------------

def test_declared_versions_agree():
    """__version__, pyproject.toml и version_info.txt обязаны совпадать.

    __version__ — единственное, что видно из собранного exe, и именно с ним
    сравнивается релиз на GitHub. Отстанет — программа начнёт бесконечно
    предлагать обновиться на уже установленное.
    """
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject_version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)

    version_info = (PROJECT_ROOT / "BoostiFy.version_info.txt").read_text(encoding="utf-8")
    file_version = re.search(r"StringStruct\('FileVersion', '([^']+)'\)", version_info).group(1)
    product_version = re.search(r"StringStruct\('ProductVersion', '([^']+)'\)", version_info).group(1)
    numeric = re.search(r"filevers=\((\d+), (\d+), (\d+), \d+\)", version_info).groups()

    assert pyproject_version == __version__
    assert file_version == __version__
    assert product_version == __version__
    assert ".".join(numeric) == __version__
