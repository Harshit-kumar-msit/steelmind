"""
Module: ai/rag/retriever.py
Purpose: Hybrid retrieval (dense ChromaDB + sparse BM25) with cross-encoder
         reranking. Returns top-K chunks with formatted citations.
Inputs:  Query string, optional equipment_id filter, optional category filter
Outputs: List of RankedChunk objects + formatted context string for LLM prompt
Implementation Steps:
  1. Dense retrieval: embed query → cosine search ChromaDB → top-15
  2. Sparse retrieval: BM25 over the same corpus → top-15
  3. Reciprocal Rank Fusion (RRF) to merge → top-10 candidates
  4. Cross-encoder rerank → final top-K (default 5)
  5. Format context block with [DOC:chunk_id] citation markers
Production: Cache frequent queries (Redis, TTL=300s).
            For multi-equipment plants, pre-filter by plant_area or
            equipment_type to keep retrieval precision high.
            Log retrieval quality: track which chunks get cited by LLM.
"""
import json
from dataclasses import dataclass, field
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi
from loguru import logger

from app.core.config import settings


@dataclass
class RankedChunk:
    chunk_id: str
    doc_id: str
    title: str
    doc_category: str
    text: str
    score: float
    rank: int
    metadata: dict = field(default_factory=dict)

    def to_citation(self) -> dict:
        """Returns a dict suitable for the frontend CitationChip component."""
        return {
            "chunk_id": self.chunk_id,
            "doc_id":   self.doc_id,
            "title":    self.title,
            "category": self.doc_category,
            "preview":  self.text[:200],
            "rank":     self.rank,
        }


class RAGRetriever:
    """
    Hybrid retriever combining dense vector search and BM25 keyword search.
    
    The combination handles two failure modes:
    - Dense-only misses: exact terminology queries ("ISO 13373-7", part numbers)
    - BM25-only misses: semantic/paraphrase queries ("what causes rumbling noise?")

    Usage:
        retriever = RAGRetriever()
        chunks = retriever.retrieve("bearing spalling symptoms", equipment_id="EQ-BF-001")
        context = retriever.format_context(chunks)
    """

    def __init__(self):
        # ── Dense encoder (same model as ingestor — must match!) ──
        self.embedder = SentenceTransformer(
            settings.embedding_model,
            trust_remote_code=True,
        )

        # ── Cross-encoder for reranking ──
        # ms-marco-MiniLM-L-6-v2 is fast (6 layers) and good for relevance ranking
        self.reranker = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            max_length=512,
        )

        # ── ChromaDB ──
        self.chroma_client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

        # ── BM25 index (built lazily from ChromaDB corpus) ──
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: list[str] = []
        self._bm25_docs: list[str] = []
        self._rebuild_bm25()

        logger.info(
            f"RAGRetriever ready | chunks={self.collection.count()} "
            f"| bm25_docs={len(self._bm25_ids)}"
        )

    # ─── Public API ───────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        equipment_id: str = "",
        doc_category: str = "",
        top_k: int = None,
        dense_k: int = 15,
        sparse_k: int = 15,
    ) -> list[RankedChunk]:
        """
        Main retrieval method.

        Args:
            query:        Engineer's question or search text
            equipment_id: If set, boost chunks tagged with this equipment
            doc_category: Filter to a specific category (manual, sop, rca, etc.)
            top_k:        Final number of chunks to return (default: settings.top_k_retrieval)
            dense_k:      Candidates from dense retrieval
            sparse_k:     Candidates from sparse retrieval

        Returns:
            List of RankedChunk sorted by relevance score (highest first)
        """
        top_k = top_k or settings.top_k_retrieval

        if self.collection.count() == 0:
            logger.warning("ChromaDB collection is empty — no documents ingested yet")
            return []

        # ── Step 1: Dense retrieval ──
        dense_results = self._dense_retrieve(query, equipment_id, doc_category, dense_k)

        # ── Step 2: Sparse retrieval (BM25) ──
        sparse_results = self._sparse_retrieve(query, equipment_id, sparse_k)

        # ── Step 3: Reciprocal Rank Fusion ──
        merged = self._reciprocal_rank_fusion(dense_results, sparse_results)

        # ── Step 4: Cross-encoder rerank ──
        if len(merged) > top_k:
            merged = self._rerank(query, merged, top_k * 2)[:top_k]
        else:
            merged = merged[:top_k]

        # ── Step 5: Assign final ranks ──
        for i, chunk in enumerate(merged):
            chunk.rank = i + 1

        return merged

    def format_context(self, chunks: list[RankedChunk]) -> str:
        """
        Format retrieved chunks into a context block for the LLM system prompt.
        Each chunk is clearly labelled with its citation ID so the LLM can cite it.

        Output example:
            [DOC:manual-bf-001__chunk_0003] — Blower Manual §4.2 Vibration Limits
            Vibration levels above 7.1 mm/s RMS indicate critical condition...

            [DOC:sop-bearing-replace__chunk_0001] — Bearing Replacement SOP
            Step 1: Isolate the equipment using lockout/tagout procedure...
        """
        if not chunks:
            return "No relevant documents found in the knowledge base."

        parts = []
        for chunk in chunks:
            header = f"[DOC:{chunk.chunk_id}] — {chunk.title} ({chunk.doc_category})"
            parts.append(f"{header}\n{chunk.text}")

        return "\n\n---\n\n".join(parts)

    def get_citations(self, chunks: list[RankedChunk]) -> list[dict]:
        """Return citation objects for the API response."""
        return [c.to_citation() for c in chunks]

    def rebuild_index(self):
        """Rebuild BM25 index — call after new documents are ingested."""
        self._rebuild_bm25()
        logger.info("BM25 index rebuilt")

    # ─── Private Methods ──────────────────────────────────────────────────────

    def _dense_retrieve(
        self, query: str, equipment_id: str, doc_category: str, k: int
    ) -> list[RankedChunk]:
        """Embed query and do cosine similarity search in ChromaDB."""
        query_embedding = self.embedder.encode(
            query, normalize_embeddings=True
        ).tolist()

        # Build where filter
        where = {}
        if equipment_id:
            # equipment_tags is a comma-joined string like "EQ-BF-001,centrifugal_compressor"
            # ChromaDB doesn't support LIKE, so we rely on reranking to boost relevance
            pass
        if doc_category:
            where["doc_category"] = doc_category

        query_kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(k, self.collection.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_kwargs["where"] = where

        results = self.collection.query(**query_kwargs)

        chunks = []
        for i, chunk_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            score = 1.0 - distance   # cosine distance → similarity

            # Equipment tag boost
            if equipment_id and equipment_id in meta.get("equipment_tags", ""):
                score = min(1.0, score * 1.15)

            chunks.append(RankedChunk(
                chunk_id=chunk_id,
                doc_id=meta.get("doc_id", ""),
                title=meta.get("title", ""),
                doc_category=meta.get("doc_category", ""),
                text=results["documents"][0][i],
                score=score,
                rank=i + 1,
                metadata=meta,
            ))
        return chunks

    def _sparse_retrieve(self, query: str, equipment_id: str, k: int) -> list[RankedChunk]:
        """BM25 keyword search over the entire corpus."""
        if not self._bm25 or not self._bm25_ids:
            return []

        query_tokens = query.lower().split()
        scores = self._bm25.get_scores(query_tokens)

        # Get top-k indices
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

        chunks = []
        for rank, idx in enumerate(top_indices):
            if scores[idx] <= 0:
                break
            chunk_id = self._bm25_ids[idx]
            # Fetch metadata from ChromaDB
            try:
                result = self.collection.get(ids=[chunk_id], include=["documents", "metadatas"])
                if not result["ids"]:
                    continue
                meta = result["metadatas"][0]
                text = result["documents"][0]
                chunks.append(RankedChunk(
                    chunk_id=chunk_id,
                    doc_id=meta.get("doc_id", ""),
                    title=meta.get("title", ""),
                    doc_category=meta.get("doc_category", ""),
                    text=text,
                    score=float(scores[idx]),
                    rank=rank + 1,
                    metadata=meta,
                ))
            except Exception:
                pass
        return chunks

    def _reciprocal_rank_fusion(
        self,
        dense: list[RankedChunk],
        sparse: list[RankedChunk],
        k: int = 60,
    ) -> list[RankedChunk]:
        """
        Merge two ranked lists using Reciprocal Rank Fusion.
        RRF score = Σ 1/(k + rank_i)
        Documents appearing in both lists get a big boost.
        """
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, RankedChunk] = {}

        for rank, chunk in enumerate(dense, 1):
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0) + 1 / (k + rank)
            chunk_map[chunk.chunk_id] = chunk

        for rank, chunk in enumerate(sparse, 1):
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0) + 1 / (k + rank)
            if chunk.chunk_id not in chunk_map:
                chunk_map[chunk.chunk_id] = chunk

        # Sort by RRF score
        sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
        result = []
        for i, cid in enumerate(sorted_ids):
            chunk = chunk_map[cid]
            chunk.score = rrf_scores[cid]
            chunk.rank = i + 1
            result.append(chunk)
        return result

    def _rerank(self, query: str, chunks: list[RankedChunk], top_n: int) -> list[RankedChunk]:
        """
        Cross-encoder reranking.
        The cross-encoder sees both the query and chunk text together
        and gives a relevance score — more accurate than bi-encoder similarity.
        """
        pairs = [(query, chunk.text) for chunk in chunks]
        scores = self.reranker.predict(pairs)

        for chunk, score in zip(chunks, scores):
            chunk.score = float(score)

        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_n]

    def _rebuild_bm25(self):
        """Build BM25 index from all documents currently in ChromaDB."""
        try:
            count = self.collection.count()
            if count == 0:
                return
            # Fetch all documents in batches
            all_ids = []
            all_docs = []
            batch_size = 1000
            offset = 0
            while True:
                batch = self.collection.get(
                    limit=batch_size,
                    offset=offset,
                    include=["documents"],
                )
                if not batch["ids"]:
                    break
                all_ids.extend(batch["ids"])
                all_docs.extend(batch["documents"])
                offset += batch_size
                if len(batch["ids"]) < batch_size:
                    break

            # Tokenize for BM25
            tokenized = [doc.lower().split() for doc in all_docs]
            self._bm25 = BM25Okapi(tokenized)
            self._bm25_ids = all_ids
            self._bm25_docs = all_docs
            logger.debug(f"BM25 index built with {len(all_ids)} chunks")
        except Exception as e:
            logger.error(f"Failed to build BM25 index: {e}")


# ─── Singleton ────────────────────────────────────────────────────────────────
_retriever_instance: Optional[RAGRetriever] = None


def get_retriever() -> RAGRetriever:
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = RAGRetriever()
    return _retriever_instance
