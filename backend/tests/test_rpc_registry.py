from types import SimpleNamespace

import pytest

from evals.service import EvalService
from main import RpcDispatcher
from rpc_contract import RPC_METHODS
from rpc_handlers.health import HealthHandlers
from rpc_registry import bind_handlers, handler_definitions, rpc


@pytest.mark.parametrize(
    "names", [(), ("session.typo",), ("session.stop", "session.stop")]
)
def test_registration_rejects_empty_unknown_and_duplicate_names(names):
    with pytest.raises(ValueError):
        rpc(*names)


def test_registration_rejects_synchronous_handlers():
    with pytest.raises(TypeError, match="async"):
        rpc("health.check")(lambda *_: None)


def test_stacked_registration_cannot_overwrite_aliases():
    @rpc("session.stop")
    async def handler(*args):
        pass

    with pytest.raises(ValueError, match="one RPC decorator"):
        rpc("session.cancel")(handler)


def test_inherited_duplicate_handlers_are_rejected_not_silently_shadowed():
    class First:
        @rpc("health.check")
        async def first(self, method, params, db):
            pass

    class Second:
        @rpc("health.check")
        async def second(self, method, params, db):
            pass

    class Combined(First, Second):
        pass

    with pytest.raises(ValueError, match="Duplicate RPC handler: health.check"):
        handler_definitions(Combined)


@pytest.mark.asyncio
async def test_aliases_and_cached_definitions_bind_to_each_services_own_state():
    class Service:
        def __init__(self, label):
            self.label = label

        @rpc("session.stop", "session.cancel")
        async def stop(self, method, params, db):
            return self.label, method, params, db

    first, second = Service("first"), Service("second")
    a, b = bind_handlers(first), bind_handlers(second)
    definitions = handler_definitions(Service)
    assert definitions is handler_definitions(Service)
    assert a["session.stop"].__func__ is a["session.cancel"].__func__
    assert a["session.stop"].__self__ is first
    assert b["session.stop"].__self__ is second
    params, db = {"session_id": 1}, object()
    assert await a["session.stop"]("session.stop", params, db) == (
        "first",
        "session.stop",
        params,
        db,
    )
    assert await b["session.cancel"]("session.cancel", params, db) == (
        "second",
        "session.cancel",
        params,
        db,
    )
    with pytest.raises(TypeError):
        a["session.stop"] = b["session.stop"]
    with pytest.raises(TypeError):
        definitions["session.stop"] = Service.stop


@pytest.mark.asyncio
async def test_all_59_methods_route_to_the_registered_domain_with_exact_arguments():
    core = handler_definitions(RpcDispatcher)
    evaluation = handler_definitions(EvalService)
    assert not core.keys() & evaluation.keys()
    assert core.keys() | evaluation.keys() == RPC_METHODS.keys()
    for method in RPC_METHODS:
        calls = []
        params, db, result = {"sentinel": method}, object(), object()

        async def handler(
            name, received_params, received_db, *, calls=calls, result=result
        ):
            calls.append((name, received_params, received_db))
            return result

        service = SimpleNamespace(_rpc_handlers={method: handler})
        service.dispatch = lambda *args, owner=service: EvalService.dispatch(
            owner, *args
        )
        dispatcher = SimpleNamespace(
            _rpc_handlers={method: handler}, eval_service=service
        )
        assert (
            await RpcDispatcher._dispatch_method(dispatcher, method, params, db)
            is result
        )
        assert calls == [(method, params, db)], method


@pytest.mark.asyncio
async def test_health_handler_is_independently_testable_without_application_startup():
    queries = []

    class Database:
        async def execute(self, statement):
            queries.append(str(statement))

    handler = bind_handlers(HealthHandlers())["health.check"]
    assert await handler("health.check", {}, Database()) == {"status": "ok"}
    assert queries == ["SELECT 1"]


@pytest.mark.asyncio
async def test_unknown_methods_remain_not_implemented_in_both_routers():
    core = SimpleNamespace(_rpc_handlers={})
    service = SimpleNamespace(_rpc_handlers={})
    with pytest.raises(NotImplementedError, match="Unknown method: workspace.typo"):
        await RpcDispatcher._dispatch_method(core, "workspace.typo", {}, None)
    with pytest.raises(NotImplementedError, match="Unknown method: eval.case.typo"):
        await EvalService.dispatch(service, "eval.case.typo", {}, None)
