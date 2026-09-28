from .anthropic_live import AnthropicProvider
from .base import AssessmentProvider, ProviderResult
from .faults import FAULT_MODES, FaultInjectionProvider
from .offline import OfflineFixtureProvider, OfflineProvider, OfflineSimulationProvider


def get_provider(mode: str):
    """mode: offline | simulation | live | fault:<mode>."""
    if mode == "offline":
        return OfflineProvider()
    if mode == "simulation":
        return OfflineSimulationProvider()
    if mode == "live":
        return AnthropicProvider()
    if mode.startswith("fault:"):
        return FaultInjectionProvider(mode.split(":", 1)[1])
    raise ValueError(f"Unknown provider mode: {mode}")


__all__ = [
    "AnthropicProvider", "AssessmentProvider", "ProviderResult", "FAULT_MODES", "FaultInjectionProvider",
    "OfflineFixtureProvider", "OfflineProvider", "OfflineSimulationProvider", "get_provider",
]
