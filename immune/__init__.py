"""IMMUNE — a self-healing immune system for agent memory.

Pipeline: provenance+trust at write -> admission gate at read -> shadow-replay
attribution of failures -> quarantine -> offline parole. The moat is replay.py.
"""
from .schemas import MemoryRecord, TurnLog
from .store import ImmuneMemory
from .agent import Agent, score
from .replay import ShadowReplay
from . import scenario

__all__ = ["MemoryRecord", "TurnLog", "ImmuneMemory", "Agent", "score",
           "ShadowReplay", "scenario"]
