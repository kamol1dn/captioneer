"""Resolve the compute device and precision for the Whisper backends."""


def resolve_device(device: str) -> str:
    """Resolve 'auto' to 'cuda' if available, else 'cpu'."""
    if device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def resolve_compute_type(compute_type: str, device: str) -> str:
    """Resolve 'auto'. float16 on GPU, int8 on CPU (float16 is unsupported there)."""
    if compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"
