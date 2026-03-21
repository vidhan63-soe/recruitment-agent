"""
Matching Engine.
Orchestrates the full RAG pipeline:
  1. Embed the job description
  2. Query vector store for similar resume chunks
  3. Score each candidate with LLM
  4. Combine semantic + LLM scores
  5. Return ranked candidates
"""

from loguru import logger

from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.services.llm_scorer import LLMScorer
from app.models.schemas import CandidateScore, MatchResult


class MatchingEngine:
    """Combines RAG retrieval with LLM scoring for candidate ranking."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        llm_scorer: LLMScorer,
    ):
        self.embedder = embedding_service
        self.store = vector_store
        self.scorer = llm_scorer

    async def match(
        self,
        jd_text: str,
        jd_title: str,
        jd_id: str,
        top_k: int = 10,
        min_score: float = 0.35,
    ) -> MatchResult:
        """
        Run the full matching pipeline.
        """
        logger.info(f"Starting match for JD: {jd_title} (top_k={top_k})")

        # Step 1: Embed the JD
        jd_embedding = self.embedder.encode_single(jd_text)

        # Step 2: RAG retrieval — find similar resume chunks
        retrieval = self.store.query(
            query_embedding=jd_embedding,
            top_k=top_k * 2,  # Fetch extra, filter later
        )

        candidates: list[CandidateScore] = []

        # Step 3: Score each candidate with LLM
        for result in retrieval["results"]:
            semantic_score = result["semantic_score"]

            # Skip very low semantic matches
            if semantic_score < min_score * 0.5:
                continue

            # LLM evaluation
            llm_result = await self.scorer.score_candidate(
                jd_text=jd_text,
                resume_chunks=result["matched_chunks"],
                candidate_name=result["candidate_name"],
            )

            # Step 4: Combine scores
            # Semantic: 40%, LLM: 60% (LLM is more nuanced)
            llm_score = llm_result["llm_score"]
            final_score = (semantic_score * 0.4) + (llm_score * 0.6)

            if final_score < min_score:
                continue

            candidates.append(
                CandidateScore(
                    resume_id=result["resume_id"],
                    candidate_name=result["candidate_name"],
                    email="",  # Will be enriched from resume store
                    filename=result["filename"],
                    semantic_score=round(semantic_score, 4),
                    llm_score=round(llm_score, 4),
                    final_score=round(final_score, 4),
                    matched_skills=llm_result.get("matched_skills", []),
                    missing_skills=llm_result.get("missing_skills", []),
                    summary=llm_result.get("summary", ""),
                )
            )

        # Step 5: Sort by final score and assign ranks
        candidates.sort(key=lambda c: c.final_score, reverse=True)
        candidates = candidates[:top_k]

        for i, candidate in enumerate(candidates):
            candidate.rank = i + 1

        logger.info(
            f"Match complete: {len(candidates)} candidates above threshold "
            f"(searched {retrieval['total_chunks_searched']} chunks)"
        )

        return MatchResult(
            jd_id=jd_id,
            jd_title=jd_title,
            total_resumes=self.store.get_total_resumes(),
            candidates=candidates,
        )
