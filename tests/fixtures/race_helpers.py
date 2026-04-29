"""Helpers for testing race conditions and concurrent operations."""

import asyncio
from collections.abc import Callable
from typing import Any


async def run_concurrently(funcs: list[Callable], n: int | None = None) -> list[tuple[Any, Exception | None]]:
    """
    Run sync functions concurrently via asyncio.to_thread.
    Returns list of (result, exception) tuples.
    n: if provided, duplicate funcs[0] n times (convenience for uniform concurrent calls).
    """
    if n is not None:
        funcs = [funcs[0]] * n

    async def call_one(fn: Callable) -> tuple[Any, Exception | None]:
        try:
            result = await asyncio.to_thread(fn)
            return (result, None)
        except Exception as exc:
            return (None, exc)

    tasks = [call_one(fn) for fn in funcs]
    return await asyncio.gather(*tasks)
