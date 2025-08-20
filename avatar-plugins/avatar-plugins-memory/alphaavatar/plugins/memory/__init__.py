from alphaavatar.agents import MemoryRegistry

from .mem0 import Memory as Mem0Memory


MemoryRegistry.register("mem0", Mem0Memory)
