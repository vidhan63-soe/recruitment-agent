"""
GPU detection and device management.
Automatically picks the best available device and reports VRAM.
"""

import torch
from loguru import logger


def get_device(preference: str = "auto") -> str:
    """
    Resolve compute device.
    preference: "auto" | "cuda" | "cpu"
    """
    if preference == "cpu":
        logger.info("Device forced to CPU by config")
        return "cpu"

    if preference in ("auto", "cuda"):
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_total = torch.cuda.get_device_properties(0).total_memory  / (1024 ** 3)
            vram_free = (
                torch.cuda.get_device_properties(0).total_memory 
                - torch.cuda.memory_reserved(0)
            ) / (1024 ** 3)

            logger.info(
                f"GPU detected: {gpu_name} | "
                f"VRAM: {vram_total:.1f}GB total, ~{vram_free:.1f}GB free"
            )

            # Warn if low VRAM
            if vram_total < 4.0:
                logger.warning(
                    f"Low VRAM ({vram_total:.1f}GB). "
                    "Consider using 'all-MiniLM-L6-v2' embedding model "
                    "and 'phi3:mini' for Ollama."
                )

            return "cuda"
        else:
            logger.warning("CUDA not available, falling back to CPU")
            return "cpu"

    logger.warning(f"Unknown device preference '{preference}', using CPU")
    return "cpu"


def log_gpu_usage(label: str = ""):
    """Log current GPU memory usage. Call this for debugging."""
    if not torch.cuda.is_available():
        return

    allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
    reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
    prefix = f"[{label}] " if label else ""
    logger.debug(f"{prefix}GPU mem — allocated: {allocated:.2f}GB, reserved: {reserved:.2f}GB")
