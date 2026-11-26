from .base import SimInterface, SimState


def create_sim(backend: str, **kwargs) -> SimInterface:
    if backend == "mock":
        from .mock import MockSim
        return MockSim(**kwargs)
    if backend == "msfs":
        from .msfs import MSFSSim
        return MSFSSim()
    raise ValueError(f"未知的 sim backend: {backend}")


__all__ = ["SimInterface", "SimState", "create_sim"]
