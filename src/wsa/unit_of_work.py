from __future__ import annotations

from types import TracebackType
from typing import Any


class WorldUnitOfWork:
    """Own one explicit world-repository transaction boundary."""

    def __init__(self, repo: Any, *, immediate: bool = False) -> None:
        self.repo = repo
        self.immediate = immediate
        self._context: Any = None
        self.connection: Any = None

    def __enter__(self) -> Any:
        self._context = self.repo._connect()
        self.connection = self._context.__enter__()
        if self.immediate:
            self.connection.execute("BEGIN IMMEDIATE")
        return self.connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._context.__exit__(exc_type, exc, traceback)
