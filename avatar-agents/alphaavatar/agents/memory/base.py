"""Global Memory Abstract Class for Avatar"""
from abc import ABC, abstractmethod

from livekit.agents.types import NOT_GIVEN, NotGivenOr


class MemoryBase(ABC):
    def __init__(
        self,
        *,
        avater_name: str,
        memory_token_length: NotGivenOr[int | None] = NOT_GIVEN,
        memory_segment_length: NotGivenOr[int | None] = NOT_GIVEN,
    ) -> None:
        super().__init__()
        self._avatar_name = avater_name
        self._memory_token_length = memory_token_length
        self._memory_segment_length = memory_segment_length

    @abstractmethod
    async def search(
        self,
        *,
        query: str
    ): ...

    @abstractmethod
    async def add(
        self,
        *,
        messages: list[dict]
    ): ...
    
    @abstractmethod
    async def update(
        self,
    ): ...
