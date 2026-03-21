"""
Embedding Service.
Manages the sentence-transformer model for generating embeddings.
Optimized for low-VRAM GPUs with batch processing.

Model choices by GPU:
  - GTX 1650 Ti (4GB): all-MiniLM-L6-v2 — 384 dims, ~80MB, ~400MB VRAM
  - RTX 3050 (6GB):    all-mpnet-base-v2 — 768 dims, ~420MB, ~1.2GB VRAM
"""

import torch
from sentence_transformers import SentenceTransformer
from loguru import logger

from app.core.gpu import log_gpu_usage


class EmbeddingService:
    """Singleton-style embedding model manager."""

    def __init__(self, model_name: str, device: str):
        self.model_name = model_name
        self.device = device
        self.model: SentenceTransformer | None = None
        self.dimension: int = 0

    def load(self):
        """Load the model onto the target device."""
        logger.info(f"Loading embedding model: {self.model_name} on {self.device}")

        self.model = SentenceTransformer(self.model_name, device=self.device)

        # Determine embedding dimension
        self.dimension = self.model.get_sentence_embedding_dimension()

        # Enable half precision on GPU to save VRAM
        if self.device == "cuda":
            self.model.half()
            log_gpu_usage("after embedding model load")

        logger.info(
            f"Embedding model loaded: dim={self.dimension}, "
            f"device={self.device}, fp16={self.device == 'cuda'}"
        )

    def encode(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> list[list[float]]:
        """
        Encode texts into embeddings.
        Uses batched encoding to avoid OOM on small GPUs.
        """
        if not self.model:
            raise RuntimeError("Embedding model not loaded. Call load() first.")

        if not texts:
            return []

        # Smaller batch size for GPU to avoid OOM
        if self.device == "cuda":
            batch_size = min(batch_size, 16)

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
            normalize_embeddings=True,  # Cosine similarity via dot product
        )

        if self.device == "cuda":
            log_gpu_usage("after encoding batch")

        return embeddings.tolist()

    def encode_single(self, text: str) -> list[float]:
        """Encode a single text string."""
        result = self.encode([text])
        return result[0] if result else []

    def unload(self):
        """Free GPU memory."""
        if self.model:
            del self.model
            self.model = None
            if self.device == "cuda":
                torch.cuda.empty_cache()
            logger.info("Embedding model unloaded")
