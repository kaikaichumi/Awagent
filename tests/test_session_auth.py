"""認證預檢欄位相容性：SDK 1.0.x 是 camelCase 的 isAuthenticated，
舊版/內部型別是 snake_case 的 is_authenticated。"""

from __future__ import annotations

from types import SimpleNamespace

from waagent.chat.session import auth_status_flag


def test_camelcase_not_authenticated():
    assert auth_status_flag(SimpleNamespace(isAuthenticated=False)) is False


def test_camelcase_authenticated():
    assert auth_status_flag(SimpleNamespace(isAuthenticated=True)) is True


def test_snakecase_fallback():
    assert auth_status_flag(SimpleNamespace(is_authenticated=False)) is False
    assert auth_status_flag(SimpleNamespace(is_authenticated=True)) is True


def test_camelcase_wins_over_snakecase():
    status = SimpleNamespace(isAuthenticated=False, is_authenticated=True)
    assert auth_status_flag(status) is False


def test_unknown_shape_returns_none():
    assert auth_status_flag(SimpleNamespace()) is None
