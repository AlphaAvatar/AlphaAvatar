"""A global Memort Module for Avatar"""
from abc import ABC, abstractmethod


class Memory(ABC):
    def __init__(
        self,
        *,
        avater_name: str
    ) -> None:
        super().__init__()
        self._avatar_name = avater_name
    
    @abstractmethod
    async def search(
        self,
        *,
        memory_id: str,
        query: str
    ): ...
    
    @abstractmethod
    async def update(
        self,
        *,
        memory_id: str,
        messages: list[dict]
    ): ...
