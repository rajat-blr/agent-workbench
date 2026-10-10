import ast
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from database import schemas
from main import RpcDispatcher
from rpc_contract import RESULT_ADAPTERS, RPC_METHODS
from tools.generate_rpc_contract import TARGET, generate, typescript


def test_registry_matches_every_handler_and_parameter_model():
    import inspect
    import textwrap

    from evals.service import EvalService
    from rpc_registry import handler_definitions

    implemented = {}
    for owner in (RpcDispatcher, EvalService):
        for name, function in handler_definitions(owner).items():
            assert name not in implemented
            implemented[name] = function
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
            for node in ast.walk(tree):
                if (
                    not isinstance(node, ast.Call)
                    or not isinstance(node.func, ast.Name)
                    or node.func.id != "_params"
                ):
                    continue
                if isinstance(node.args[0], ast.Name):
                    model = function.__globals__.get(node.args[0].id)
                    if isinstance(model, type) and issubclass(model, schemas.BaseModel):
                        assert RPC_METHODS[name].params is model
    assert implemented.keys() == RPC_METHODS.keys()


def test_generated_types_are_deterministic_and_up_to_date():
    assert generate() == generate() == TARGET.read_text()
    generated = generate()
    assert (
        '"session.create": { params: InputSessionCreate; result: SessionRecord }'
        in generated
    )
    assert '"provider"?: "codex"' in generated
    assert '"created_at": string' in generated
    assert '"latest_revision": EvalCaseRevision | null' in generated


def test_inputs_share_pydantic_defaults_constraints_and_nullable_fields():
    params = RPC_METHODS["session.create"].params.model_validate({"workspace_id": 1})
    assert params.provider == "codex"
    assert (
        RPC_METHODS["eval.config.capture"]
        .params.model_validate({"name": "Baseline", "model": None})
        .model
        is None
    )
    with pytest.raises(ValidationError):
        RPC_METHODS["session.list"].params.model_validate({"workspace_id": 0})
    with pytest.raises(ValidationError):
        RPC_METHODS["workspace.git_commit"].params.model_validate(
            {
                "workspace_id": 1,
                "expected_branch": "main",
                "message": "Change",
                "index_token": "invalid",
            }
        )


def test_schema_conversion_is_fail_closed_for_unsupported_constructs():
    assert (
        typescript({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "string | null"
    )
    assert (
        typescript({"type": "object", "additionalProperties": {"type": "integer"}})
        == "Record<string, number>"
    )
    with pytest.raises(ValueError, match="Unsupported"):
        typescript({"oneOf": [{"type": "string"}, {"type": "number"}]})


@pytest.mark.asyncio
async def test_dispatch_rejects_invalid_inputs_before_handler_execution():
    called = []

    async def handler(*args):
        called.append(args)

    dispatcher = SimpleNamespace(_dispatch_method=handler)
    result = await RpcDispatcher.dispatch(
        dispatcher,
        schemas.RpcRequest(id=7, method="session.send", params={"session_id": 1}),
        None,
    )
    assert result["id"] == 7
    assert result["error"]["code"] == -32602
    unknown = await RpcDispatcher.dispatch(
        dispatcher, schemas.RpcRequest(id=8, method="session.typo"), None
    )
    assert unknown["error"]["code"] == -32601
    assert called == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, params, payload",
    [
        ("health.check", {}, {"status": "broken"}),
        (
            "session.send",
            {"session_id": 1, "content": "Hi"},
            {"accepted": True, "session_id": 1, "run_id": "2"},
        ),
        (
            "session.send",
            {"session_id": 1, "content": "Hi"},
            {"accepted": True, "session_id": 1},
        ),
        (
            "workspace.list",
            {},
            [{"id": 1, "path": "/fixture", "name": "Test", "created_at": None}],
        ),
        ("health.check", {}, {"status": object()}),
    ],
)
async def test_response_mismatch_is_internal_error_without_payload_details(
    method, params, payload
):
    async def handler(*args):
        return payload

    dispatcher = SimpleNamespace(_dispatch_method=handler)
    response = await RpcDispatcher.dispatch(
        dispatcher, schemas.RpcRequest(id=9, method=method, params=params), None
    )
    assert response == {
        "jsonrpc": "2.0",
        "id": 9,
        "error": {"code": -32603, "message": "Response contract mismatch"},
    }


@pytest.mark.asyncio
async def test_response_validation_preserves_the_original_wire_payload():
    payload = {"status": "ok"}

    async def handler(*args):
        return payload

    response = await RpcDispatcher.dispatch(
        SimpleNamespace(_dispatch_method=handler),
        schemas.RpcRequest(id=1, method="health.check"),
        None,
    )
    assert response["result"] is payload


def test_optional_diff_fields_and_nullable_case_revision_match_wire_behavior():
    diff = {
        "run_id": 1,
        "status": "unavailable",
        "final": True,
        "reason": "No earlier diff",
        "files": [],
        "file_count": 0,
        "added": 0,
        "deleted": 0,
        "captured_at": None,
    }
    assert RESULT_ADAPTERS["run.diff.get"].validate_python(diff) == diff
    case = {
        "id": 1,
        "title": "No revision",
        "description": "",
        "created_at": "2026-10-09",
        "updated_at": "2026-10-09",
        "latest_revision": None,
    }
    assert RESULT_ADAPTERS["eval.case.get"].validate_python(case) == case
