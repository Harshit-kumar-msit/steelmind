"""
Module: ai/rag/ingestor.py
Purpose: Ingest documents (PDF, DOCX, TXT) into ChromaDB vector store.
         Parses → cleans → chunks → embeds → stores with rich metadata.
Inputs:  File paths or raw text strings + metadata dict
Outputs: ChromaDB collection populated with searchable chunks
Implementation Steps:
  1. Parse raw file to plain text (PDF via PyMuPDF, DOCX via python-docx)
  2. Clean text (remove headers/footers, fix encoding, normalise whitespace)
  3. Split into overlapping chunks (512 tokens, 64 overlap)
  4. Embed each chunk via sentence-transformers nomic-embed-text
  5. Upsert into ChromaDB with metadata: {doc_id, title, section, page,
     equipment_tags, doc_category, plant_area}
  6. Return ingestion summary
Production: Replace sentence-transformers with a local Ollama embedding
            endpoint so the embedding model runs on-premise.
            Add document versioning — hash the content and skip re-embedding
            unchanged documents. Use batched upserts (256 chunks/batch).
"""
import os
import re
import uuid
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from loguru import logger

from app.core.config import settings


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class DocumentMeta:
    doc_id: str
    title: str
    doc_category: str          # manual | sop | rca | checklist | standard | inventory
    equipment_tags: list[str]  # e.g. ["EQ-BF-001", "centrifugal_compressor"]
    plant_area: str = "general"
    source_file: str = ""
    author: str = ""
    version: str = "1.0"
    extra: dict = field(default_factory=dict)


@dataclass
class TextChunk:
    chunk_id: str
    doc_id: str
    text: str
    metadata: dict
    token_count: int = 0


# ─── RAG Ingestor Class ───────────────────────────────────────────────────────

class RAGIngestor:
    """
    Handles the full document ingestion pipeline:
    parse → clean → chunk → embed → store.

    Usage:
        ingestor = RAGIngestor()
        await ingestor.ingest_file("manuals/blower_manual.pdf", meta)
        # or
        await ingestor.ingest_text("bearing installation procedure...", meta)
    """

    def __init__(self):
        # ── Embedding model (runs locally, no API cost) ──
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        self.embedder = SentenceTransformer(
            settings.embedding_model,
            trust_remote_code=True,   # required for nomic-embed-text
        )
        self.embed_dim = self.embedder.get_sentence_embedding_dimension()

        # ── ChromaDB client ──
        self.chroma_client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"ChromaDB ready | collection={settings.chroma_collection} "
            f"| existing_docs={self.collection.count()}"
        )

    # ─── Public API ───────────────────────────────────────────────────────────

    def ingest_file(self, file_path: str, meta: DocumentMeta) -> dict:
        """Parse a file and ingest all its chunks."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            text = self._parse_pdf(file_path)
        elif suffix in (".docx", ".doc"):
            text = self._parse_docx(file_path)
        elif suffix in (".txt", ".md"):
            text = path.read_text(encoding="utf-8", errors="ignore")
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        return self.ingest_text(text, meta)

    def ingest_text(self, text: str, meta: DocumentMeta) -> dict:
        """Ingest raw text string — main ingestion method."""
        # 1. Clean
        text = self._clean_text(text)
        if len(text) < 50:
            logger.warning(f"Document {meta.doc_id} has very little text ({len(text)} chars)")
            return {"doc_id": meta.doc_id, "chunks": 0, "status": "skipped_too_short"}

        # 2. Check if already ingested (by content hash)
        content_hash = hashlib.md5(text.encode()).hexdigest()
        existing = self.collection.get(where={"content_hash": content_hash})
        if existing["ids"]:
            logger.info(f"Document {meta.doc_id} already ingested (hash match), skipping.")
            return {"doc_id": meta.doc_id, "chunks": 0, "status": "skipped_duplicate"}

        # 3. Delete old version of this doc_id if exists
        self._delete_by_doc_id(meta.doc_id)

        # 4. Chunk
        chunks = self._chunk_text(text, meta, content_hash)
        if not chunks:
            return {"doc_id": meta.doc_id, "chunks": 0, "status": "error_no_chunks"}

        # 5. Embed in batches of 64
        batch_size = 64
        total_inserted = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts      = [c.text for c in batch]
            ids        = [c.chunk_id for c in batch]
            metadatas  = [c.metadata for c in batch]

            embeddings = self.embedder.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                normalize_embeddings=True,   # cosine similarity works best with normalized
            ).tolist()

            self.collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            total_inserted += len(batch)

        logger.info(f"Ingested doc={meta.doc_id} | chunks={total_inserted} | title={meta.title}")
        return {
            "doc_id": meta.doc_id,
            "title": meta.title,
            "chunks": total_inserted,
            "status": "ok",
        }

    def ingest_directory(self, directory: str, default_category: str = "manual") -> list[dict]:
        """Ingest all supported files in a directory."""
        results = []
        for path in Path(directory).rglob("*"):
            if path.suffix.lower() not in (".pdf", ".docx", ".txt", ".md"):
                continue
            meta = DocumentMeta(
                doc_id=f"doc-{path.stem.lower().replace(' ', '-')}",
                title=path.stem.replace("_", " ").replace("-", " ").title(),
                doc_category=default_category,
                equipment_tags=[],
                source_file=str(path),
            )
            try:
                result = self.ingest_file(str(path), meta)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to ingest {path}: {e}")
                results.append({"doc_id": meta.doc_id, "status": f"error: {e}"})
        return results

    def get_stats(self) -> dict:
        return {
            "total_chunks": self.collection.count(),
            "collection_name": settings.chroma_collection,
            "embedding_model": settings.embedding_model,
            "embed_dim": self.embed_dim,
        }

    # ─── Private Helpers ──────────────────────────────────────────────────────

    def _parse_pdf(self, file_path: str) -> str:
        """Extract text from PDF preserving section structure."""
        doc = fitz.open(file_path)
        pages = []
        for page_num, page in enumerate(doc, 1):
            text = page.get_text("text")
            if text.strip():
                pages.append(f"[Page {page_num}]\n{text}")
        doc.close()
        return "\n\n".join(pages)

    def _parse_docx(self, file_path: str) -> str:
        """Extract text from DOCX preserving heading hierarchy."""
        doc = DocxDocument(file_path)
        sections = []
        for para in doc.paragraphs:
            if para.text.strip():
                # Detect headings
                if para.style.name.startswith("Heading"):
                    sections.append(f"\n## {para.text}\n")
                else:
                    sections.append(para.text)
        return "\n".join(sections)

    def _clean_text(self, text: str) -> str:
        """Remove noise from extracted text."""
        # Remove excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        # Remove page numbers like "- 14 -" or "Page 14 of 50"
        text = re.sub(r"-\s*\d+\s*-", "", text)
        text = re.sub(r"Page \d+ of \d+", "", text, flags=re.IGNORECASE)
        # Fix common PDF extraction artifacts
        text = text.replace("\x00", "")
        text = text.replace("\ufffd", "")
        return text.strip()

    def _chunk_text(
        self, text: str, meta: DocumentMeta, content_hash: str
    ) -> list[TextChunk]:
        """
        Recursive character text splitter.
        Tries to split on paragraph → sentence → word boundaries.
        Target: ~512 tokens (≈ 384 words). Overlap: ~64 tokens (≈ 48 words).

        Each chunk retains full metadata for retrieval-time filtering.
        """
        target_words = int(settings.chunk_size * 0.75)   # tokens ≈ words * 1.33
        overlap_words = int(settings.chunk_overlap * 0.75)

        words = text.split()
        if not words:
            return []

        chunks = []
        start = 0
        chunk_index = 0

        while start < len(words):
            end = min(start + target_words, len(words))
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)

            # Try to end at a sentence boundary
            last_period = chunk_text.rfind(". ")
            if last_period > len(chunk_text) * 0.6:
                chunk_text = chunk_text[:last_period + 1]

            chunk_id = f"{meta.doc_id}__chunk_{chunk_index:04d}"
            chunk = TextChunk(
                chunk_id=chunk_id,
                doc_id=meta.doc_id,
                text=chunk_text,
                token_count=len(chunk_words),
                metadata={
                    # Core identifiers
                    "chunk_id":       chunk_id,
                    "doc_id":         meta.doc_id,
                    "title":          meta.title,
                    "doc_category":   meta.doc_category,
                    "chunk_index":    chunk_index,
                    # Filtering fields
                    "plant_area":     meta.plant_area,
                    "equipment_tags": ",".join(meta.equipment_tags),  # Chroma needs strings
                    "source_file":    meta.source_file,
                    "author":         meta.author,
                    "version":        meta.version,
                    "content_hash":   content_hash,
                    # Display fields
                    "preview":        chunk_text[:200],
                },
            )
            chunks.append(chunk)

            # Move start forward, keeping overlap
            actual_words_used = len(chunk_text.split())
            start += max(1, actual_words_used - overlap_words)
            chunk_index += 1

        return chunks

    def _delete_by_doc_id(self, doc_id: str) -> int:
        """Delete all chunks for a given doc_id (for re-ingestion)."""
        try:
            existing = self.collection.get(where={"doc_id": doc_id})
            if existing["ids"]:
                self.collection.delete(ids=existing["ids"])
                logger.info(f"Deleted {len(existing['ids'])} old chunks for doc_id={doc_id}")
                return len(existing["ids"])
        except Exception:
            pass
        return 0


# ─── Singleton ────────────────────────────────────────────────────────────────
_ingestor_instance: Optional[RAGIngestor] = None


def get_ingestor() -> RAGIngestor:
    global _ingestor_instance
    if _ingestor_instance is None:
        _ingestor_instance = RAGIngestor()
    return _ingestor_instance
