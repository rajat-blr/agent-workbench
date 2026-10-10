import subprocess

import pytest

from tools.local_rpc import ROOT, connection_for_process


def test_connection_uses_confirmed_database_and_keeps_token_in_memory(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "state.db"

    def run(argv, **kwargs):
        output = (
            f"p123\nf10\nn{database}\n"
            if argv[0] == "lsof"
            else f"python {ROOT}/backend/main.py LOCAL_AUTH_TOKEN=test-secret PORT=49175 X=other-secret"
        )
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr(subprocess, "run", run)
    assert connection_for_process(123, database) == (
        "http://127.0.0.1:49175",
        "test-secret",
    )
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_connection_refuses_wrong_database_before_reading_environment(
    tmp_path, monkeypatch
):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv[0])
        return subprocess.CompletedProcess(
            argv, 0, stdout="p123\nf10\nn/some/other.db\n"
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="expected database"):
        connection_for_process(123, tmp_path / "state.db")
    assert calls == ["lsof"]
