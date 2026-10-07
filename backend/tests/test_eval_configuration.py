import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from evals.configuration import (
    capture_instruction_files,
    controlled_execution,
    detect_cli_version,
    redact_text,
    reproducibility_warnings,
)


def test_only_explicit_controls_affect_execution() -> None:
    sandbox, preamble, overrides = controlled_execution(
        [
            {"kind": "file", "content": "Observed only"},
            {"kind": "preamble", "content": "Controlled instruction"},
        ],
        {"feature": True, "api_token": "[REDACTED]"},
        {"mode": "read-only", "network": False},
    )
    assert sandbox == "read-only"
    assert preamble == "Controlled instruction"
    assert overrides == ("sandbox_workspace_write.network_access=false",)


@pytest.mark.parametrize(
    "config,policy",
    [
        ({}, {"mode": "danger-full-access"}),
        ({}, {"network": True}),
        ({"sandbox_workspace_write.network_access": True}, {}),
        ({"approval_policy": "never"}, {}),
    ],
)
def test_unsafe_or_unsupported_policies_are_rejected(config, policy) -> None:
    with pytest.raises(ValueError):
        controlled_execution([], config, policy)


def test_observed_inputs_are_disclosed() -> None:
    warnings = reproducibility_warnings(
        SimpleNamespace(
            model=None,
            cli_version=None,
            codex_config_json={"feature": True},
            instructions_json=[{"path": "AGENTS.md"}],
            uncontrolled_inputs_json=[],
        )
    )
    assert any("Default model" in warning for warning in warnings)
    assert any("CLI version" in warning for warning in warnings)
    assert any("not applied" in warning for warning in warnings)
    assert any("Instruction files are observed" in warning for warning in warnings)


def test_capture_order_override_empty_and_redaction(tmp_path) -> None:
    global_dir = tmp_path / "profile"
    root = tmp_path / "repo"
    nested = root / "nested"
    global_dir.mkdir()
    nested.mkdir(parents=True)
    (global_dir / "AGENTS.override.md").write_text("  \n")
    (global_dir / "AGENTS.md").write_text("Global guidance")
    (root / "AGENTS.md").write_text("Root guidance\nAPI_KEY=must-not-persist\n")
    (nested / "AGENTS.md").write_text("Ignored")
    (nested / "AGENTS.override.md").write_text("Nested override")
    files, notices = capture_instruction_files(nested, root, global_dir)
    assert [item["path"] for item in files] == [
        "$CODEX_HOME/AGENTS.md",
        "./AGENTS.md",
        "nested/AGENTS.override.md",
    ]
    assert [item["ordinal"] for item in files] == [0, 1, 2]
    assert "must-not-persist" not in str(files)
    assert files[1]["redacted"] is True
    assert notices
    assert all(item["control"] == "observed" for item in files)


def test_capture_skips_symlinks_and_caps_content(tmp_path) -> None:
    profile = tmp_path / "profile"
    root = tmp_path / "repo"
    profile.mkdir()
    root.mkdir()
    secret = tmp_path / "outside"
    secret.write_text("do-not-read")
    (profile / "AGENTS.override.md").symlink_to(secret)
    (root / "AGENTS.md").write_text("a" * 40000)
    files, notices = capture_instruction_files(root, root, profile)
    assert len(files) == 1 and files[0]["truncated"] is True
    assert len(files[0]["content"]) == 32768
    assert "do-not-read" not in str(files)
    assert len(notices) >= 2


def test_free_text_redaction() -> None:
    assert "sensitive" not in redact_text("password: sensitive\nNormal guidance")
    assert "Normal guidance" in redact_text("password: sensitive\nNormal guidance")
    assert "sk-" not in redact_text("Use sk-abcdefghijklmnop1234")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output,expected",
    [
        (b"codex-cli 1.2.3\n", "codex-cli 1.2.3"),
        (b"untrusted text", None),
        (b"x" * 500, None),
    ],
)
async def test_cli_version_probe_is_bounded(monkeypatch, output, expected) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(output)
    reader.feed_eof()
    process = SimpleNamespace(
        stdout=reader, returncode=0, wait=AsyncMock(return_value=0)
    )
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert await detect_cli_version("configured-codex") == expected
    assert spawn.call_args.args == ("configured-codex", "--version")


@pytest.mark.asyncio
async def test_missing_cli_is_not_a_capture_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)
    )
    assert await detect_cli_version("missing-codex") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
async def test_cli_probe_reaps_process_on_timeout_or_cancellation(
    monkeypatch, failure
) -> None:
    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(side_effect=failure)),
        returncode=None,
        kill=Mock(),
        wait=AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    if failure is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await detect_cli_version("codex")
    else:
        assert await detect_cli_version("codex") is None
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
