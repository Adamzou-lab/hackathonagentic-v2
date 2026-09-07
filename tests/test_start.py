import getpass
import os
import stat
import sys

import pytest

import start


def test_secret_file_is_private_and_replaced(tmp_path):
    path = tmp_path / ".env"
    start.write_private(path, "old")
    start.write_private(path, "new")
    assert path.read_text() == "new"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".lockin-secret-*"))


def test_visible_password_fallback_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(start, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["start.py"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def unavailable(prompt):
        import warnings
        warnings.warn("Cannot hide input", getpass.GetPassWarning)
        pytest.fail("Visible input must never be reached")

    monkeypatch.setattr(getpass, "getpass", unavailable)
    with pytest.raises(SystemExit) as error:
        start.main()
    assert error.value.code == 1
    assert not (tmp_path / ".env").exists()
    assert "terminal interactif" in capsys.readouterr().err
