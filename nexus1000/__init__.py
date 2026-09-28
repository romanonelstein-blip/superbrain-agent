"""Self-contained NEXUS-1000 reference runtime used by SuperBrain CI.

The package intentionally exposes the same public bridge contract used by
python/nexus_bridge_runner.py so CI can verify the full decision chain without
relying on an untracked local filesystem.
"""

from .models import Evidence, Stance
from .orchestrator import NexusOrchestrator

__all__ = ["Evidence", "Stance", "NexusOrchestrator"]
