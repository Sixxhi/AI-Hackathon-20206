"""IMMUNE — a self-healing immune system for agent memory.

Pipeline: provenance+trust at write -> admission gate at read -> shadow-replay
attribution of failures -> quarantine -> offline parole. The moat is replay.py.
"""
from .schemas import MemoryRecord, TurnLog
from .store import ImmuneMemory
from .agent import Agent, score
from .replay import ShadowReplay
from .attribution import Attributor
from .provenance import ProvenanceGraph
from .detectors import ContradictionDetector, SelfConsistencyDetector, Suspicion
from . import scenario, redteam, embed

__all__ = ["MemoryRecord", "TurnLog", "ImmuneMemory", "Agent", "score",
           "ShadowReplay", "Attributor", "ProvenanceGraph",
           "ContradictionDetector", "SelfConsistencyDetector", "Suspicion",
           "scenario", "redteam", "embed"]
