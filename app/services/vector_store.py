"""
Vector Store Service.
Wraps ChromaDB for storing and querying resume embeddings.
Fully local — no external server needed.
"""

import json
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger

from app.services.embedding_service import EmbeddingService


class VectorStoreService:
    """Manages ChromaDB collection for resume chunks."""

    def __init__(self, persist_dir: str, collection_name: str):
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name
        self.client: chromadb.ClientAPI | None = None
        self.collection = None

    def initialize(self):
        """Create or load the ChromaDB instance."""
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        count = self.collection.count()
        logger.info(
            f"Vector store initialized: {self.persist_dir} | "
            f"Collection: {self.collection_name} | Existing chunks: {count}"
        )

    def add_resume_chunks(
        self,
        chunks: list[dict],
        embeddings: list[list[float]],
    ):
        """
        Store resume chunks with their embeddings.
        chunks: list of chunk dicts with chunk_id, resume_id, text, metadata
        embeddings: corresponding embedding vectors
        """
        if not chunks or not embeddings:
            return

        ids = [c["chunk_id"] for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = []

        for c in chunks:
            meta = {
                "resume_id": c["resume_id"],
                "chunk_index": c["chunk_index"],
                "filename": c["metadata"].get("filename", ""),
                "candidate_name": c["metadata"].get("candidate_name", ""),
                "section": c["metadata"].get("section", "general"),
            }
            metadatas.append(meta)

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        logger.info(f"Stored {len(chunks)} chunks for resume {chunks[0]['resume_id']}")

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        where_filter: dict | None = None,
    ) -> dict:
        """
        Query the vector store for similar resume chunks.
        Returns results grouped by resume_id with scores.
        """
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k * 5, 100),  # Fetch extra to aggregate per resume
            "include": ["documents", "metadatas", "distances"],
        }

        if where_filter:
            kwargs["where"] = where_filter

        results = self.collection.query(**kwargs)

        # Aggregate by resume — average score across chunks
        resume_scores: dict[str, dict] = {}

        if results and results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                distance = results["distances"][0][i]
                # ChromaDB cosine distance: 0 = identical, 2 = opposite
                # Convert to similarity score: 1 - (distance / 2)
                similarity = 1.0 - (distance / 2.0)
                resume_id = meta["resume_id"]

                if resume_id not in resume_scores:
                    resume_scores[resume_id] = {
                        "resume_id": resume_id,
                        "candidate_name": meta.get("candidate_name", "Unknown"),
                        "filename": meta.get("filename", ""),
                        "scores": [],
                        "matched_chunks": [],
                    }

                resume_scores[resume_id]["scores"].append(similarity)
                resume_scores[resume_id]["matched_chunks"].append({
                    "text": results["documents"][0][i],
                    "score": similarity,
                    "section": meta.get("section", ""),
                })

        # Compute average score and sort
        aggregated = []
        for rid, data in resume_scores.items():
            scores = data["scores"]
            # Weighted: top chunk counts more
            scores_sorted = sorted(scores, reverse=True)
            # Top-3 weighted average
            top_scores = scores_sorted[:3]
            weights = [0.5, 0.3, 0.2][: len(top_scores)]
            avg_score = sum(s * w for s, w in zip(top_scores, weights)) / sum(
                weights[: len(top_scores)]
            )

            data["semantic_score"] = round(avg_score, 4)
            # Keep only top 3 chunks for context
            data["matched_chunks"] = sorted(
                data["matched_chunks"], key=lambda x: x["score"], reverse=True
            )[:3]
            del data["scores"]
            aggregated.append(data)

        aggregated.sort(key=lambda x: x["semantic_score"], reverse=True)

        return {"results": aggregated[:top_k], "total_chunks_searched": self.collection.count()}

    def get_resume_ids(self) -> list[str]:
        """Get all unique resume IDs in the store."""
        if not self.collection or self.collection.count() == 0:
            return []

        all_meta = self.collection.get(include=["metadatas"])
        ids = set()
        for meta in all_meta["metadatas"]:
            ids.add(meta["resume_id"])
        return list(ids)

    def delete_resume(self, resume_id: str):
        """Remove all chunks for a resume."""
        # Get chunk IDs for this resume
        results = self.collection.get(
            where={"resume_id": resume_id},
            include=[],
        )
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
            logger.info(f"Deleted {len(results['ids'])} chunks for resume {resume_id}")

    def get_total_resumes(self) -> int:
        """Count unique resumes."""
        return len(self.get_resume_ids())

    def reset(self):
        """Wipe the entire collection."""
        if self.client and self.collection:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.warning("Vector store reset — all data deleted")
