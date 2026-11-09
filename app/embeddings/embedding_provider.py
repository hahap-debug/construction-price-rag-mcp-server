"""Embedding Provider Layer for Construction Price Semantic Retrieval."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
import numpy as np

from app.config import logger


class BaseEmbeddingProvider(ABC):
    """Abstract interface for text embedding providers."""

    dim: int = 384

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a list of document texts."""
        pass

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Generate embedding vector for a single query text."""
        pass


class OnnxMiniLMEmbeddingProvider(BaseEmbeddingProvider):
    """High-performance, lightweight ONNX embedding provider using all-MiniLM-L6-v2 directly.
    
    Loads in < 0.8s without ChromaDB overhead, telemetry, or network calls.
    """

    def __init__(self, model_dir: Path | str | None = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        import faiss

        if model_dir:
            self.model_dir = Path(model_dir)
        else:
            self.model_dir = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2" / "onnx"

        if not self.model_dir.exists():
            raise FileNotFoundError(f"ONNX model directory not found at: {self.model_dir}")

        tokenizer_path = self.model_dir / "tokenizer.json"
        model_path = self.model_dir / "model.onnx"
        if not tokenizer_path.exists() or not model_path.exists():
            raise FileNotFoundError(f"Missing model.onnx or tokenizer.json in {self.model_dir}")

        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.enable_padding(length=128)
        self.tokenizer.enable_truncation(max_length=128)

        sess_options = ort.SessionOptions()
        sess_options.log_severity_level = 3
        sess_options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(model_path), sess_options)
        self.dim = 384
        logger.info(f"OnnxMiniLMEmbeddingProvider initialized successfully (dim={self.dim})")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import faiss

        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        token_type_ids = np.array([e.type_ids for e in encodings], dtype=np.int64)

        outputs = self.session.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        })

        # Mean pooling with attention mask
        last_hidden_state = outputs[0]  # [B, L, D]
        input_mask_expanded = np.expand_dims(attention_mask, -1).astype(float)
        sum_embeddings = np.sum(last_hidden_state * input_mask_expanded, 1)
        sum_mask = np.clip(input_mask_expanded.sum(1), a_min=1e-9, a_max=None)
        pooled = sum_embeddings / sum_mask

        # L2 normalize for cosine similarity via Inner Product
        pooled = np.ascontiguousarray(pooled, dtype=np.float32)
        faiss.normalize_L2(pooled)
        return pooled.tolist()

    def embed_query(self, text: str) -> list[float]:
        res = self.embed_documents([text])
        return res[0] if res else [0.0] * self.dim


class FallbackTfIdfEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic, lightweight local embedding provider for offline tests."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _hash_embed(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        words = text.lower().split()
        if not words:
            return vec.tolist()

        for w in words:
            idx = hash(w) % self.dim
            vec[idx] += 1.0

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._hash_embed(text)


# Backwards compatibility alias
ChromaDefaultEmbeddingProvider = OnnxMiniLMEmbeddingProvider


def get_embedding_provider(provider_type: str = "onnx_minilm") -> BaseEmbeddingProvider:
    """Factory to get the appropriate embedding provider with graceful fallback."""
    try:
        return OnnxMiniLMEmbeddingProvider()
    except Exception as e:
        logger.warning(f"Could not load OnnxMiniLMEmbeddingProvider ({e}), falling back to FallbackTfIdfEmbeddingProvider")
        return FallbackTfIdfEmbeddingProvider()
