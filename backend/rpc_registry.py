"""Explicit async RPC handler registration, with no import-time global registry."""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from functools import cache
from types import MappingProxyType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rpc_contract import RPC_METHODS

Handler = Callable[[str, dict[str, Any], AsyncSession], Awaitable[Any]]


def rpc(*methods: str):
    """Register a handler's public names; aliases share the same implementation."""
    if not methods or len(methods) != len(set(methods)):
        raise ValueError("RPC handler needs distinct method names")
    unknown = set(methods) - RPC_METHODS.keys()
    if unknown:
        raise ValueError(f"Unrecognized RPC methods: {sorted(unknown)}")

    def decorate(function):
        if not inspect.iscoroutinefunction(function):
            raise TypeError("RPC handlers must be async")
        if hasattr(function, "__rpc_methods__"):
            raise ValueError("Use one RPC decorator with all aliases")
        function.__rpc_methods__ = methods
        return function

    return decorate


@cache
def handler_definitions(owner_type: type) -> Mapping[str, Callable]:
    handlers = {}
    for base in owner_type.__mro__:
        for function in vars(base).values():
            for method in getattr(function, "__rpc_methods__", ()):
                if method in handlers:
                    raise ValueError(f"Duplicate RPC handler: {method}")
                handlers[method] = function
    return MappingProxyType(handlers)


def bind_handlers(owner: object) -> Mapping[str, Handler]:
    """Bind cached definitions to this service, never another service's state."""
    return MappingProxyType(
        {
            name: function.__get__(owner, type(owner))
            for name, function in handler_definitions(type(owner)).items()
        }
    )
