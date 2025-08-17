import importlib
import os
import pickle
import sys
import tempfile
from collections.abc import Set
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar, Union

from .base import Memory


__all__ = [
    "Memory",
]


# logger = init_logger(__name__)

_T = TypeVar("_T")


@dataclass
class _MemoryRegistry:
    modules: dict[str, Memory] = field(default_factory=dict)

    def get_supported_memory(self) -> Set[str]:
        return self.modules.keys()

    def register_model(
        self,
        module_name: str,
        module_cls: Memory,
    ) -> None:
        self.modules[module_name] = module_cls


ModelRegistry = _MemoryRegistry()
