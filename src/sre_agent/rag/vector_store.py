"""Optional sqlite-vec storage for hybrid retrieval."""

from collections.abc import Iterable
from pathlib import Path
import hashlib
import json
import sqlite3

from sre_agent.core.settings import AgentSettings
from sre_agent.rag.models import RetrievalChunk, RetrievalMatch

try:
    import sqlite_vec
except ImportError:
    sqlite_vec = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None


class LocalEmbeddingModel:
    """Lazy wrapper around a local sentence-transformers model."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self._model = None

    def is_available(self) -> bool:
        """Return whether the embedding runtime is importable."""

        return SentenceTransformer is not None

    def embed_query(self, text: str) -> list[float]:
        """Embed a query string."""

        model = self._ensure_model()
        if hasattr(model, "encode_query"):
            vector = model.encode_query(text, normalize_embeddings=True)
        else:
            vector = model.encode(text, normalize_embeddings=True)
        return _to_float_list(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document strings."""

        model = self._ensure_model()
        if hasattr(model, "encode_document"):
            vectors = model.encode_document(texts, normalize_embeddings=True)
        else:
            vectors = model.encode(texts, normalize_embeddings=True)
        return [_to_float_list(vector) for vector in vectors]

    def _ensure_model(self):
        if self._model is None:
            if SentenceTransformer is None:
                raise RuntimeError("sentence-transformers is not installed.")
            self._model = SentenceTransformer(self.settings.rag_embedding_model)
        return self._model


class SQLiteVecIndex:
    """Persist retrieval chunks and optional embeddings in sqlite-vec."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.embedder = LocalEmbeddingModel(settings)

    def is_available(self) -> bool:
        """Return whether vector retrieval can run."""

        return sqlite_vec is not None and self.embedder.is_available()

    def search(
        self,
        *,
        corpus: str,
        source_path: str,
        chunks: list[RetrievalChunk],
        query: str,
        top_k: int,
    ) -> list[RetrievalMatch]:
        """Return vector matches for the given corpus when available."""

        if not self.is_available() or not chunks:
            return []

        db_path = self._database_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(db_path) as connection:
                if not _load_sqlite_vec(connection):
                    return []
                self._initialise_schema(connection)
                self._ensure_index(
                    connection,
                    corpus=corpus,
                    source_path=source_path,
                    chunks=chunks,
                )
                query_embedding = self.embedder.embed_query(query)
                return self._search_embeddings(
                    connection,
                    corpus=corpus,
                    query_embedding=query_embedding,
                    top_k=top_k,
                )
        except Exception:
            return []

    def _ensure_index(
        self,
        connection: sqlite3.Connection,
        *,
        corpus: str,
        source_path: str,
        chunks: list[RetrievalChunk],
    ) -> None:
        signature = _source_signature(source_path, chunks)
        current = connection.execute(
            "SELECT source_signature FROM rag_corpus_state WHERE corpus = ? AND source_path = ?",
            (corpus, source_path),
        ).fetchone()
        if current is not None and current[0] == signature:
            return

        self._replace_corpus(connection, corpus=corpus, source_path=source_path, chunks=chunks, signature=signature)

    def _replace_corpus(
        self,
        connection: sqlite3.Connection,
        *,
        corpus: str,
        source_path: str,
        chunks: list[RetrievalChunk],
        signature: str,
    ) -> None:
        embeddings = self.embedder.embed_documents([chunk.content for chunk in chunks])
        existing_rows = connection.execute(
            "SELECT rowid FROM rag_chunks WHERE corpus = ? AND source_path = ?",
            (corpus, source_path),
        ).fetchall()
        for row in existing_rows:
            connection.execute("DELETE FROM rag_vectors WHERE rowid = ?", (row[0],))
        connection.execute(
            "DELETE FROM rag_chunks WHERE corpus = ? AND source_path = ?",
            (corpus, source_path),
        )

        for chunk, embedding in zip(chunks, embeddings, strict=False):
            cursor = connection.execute(
                """
                INSERT INTO rag_chunks (
                    chunk_id,
                    corpus,
                    source_path,
                    file_path,
                    start_line,
                    end_line,
                    content,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.chunk_id,
                    corpus,
                    source_path,
                    chunk.file_path,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.content,
                    json.dumps(chunk.metadata, ensure_ascii=False),
                ),
            )
            rowid = cursor.lastrowid
            connection.execute(
                "INSERT INTO rag_vectors (rowid, embedding) VALUES (?, ?)",
                (rowid, sqlite_vec.serialize_float32(embedding)),
            )

        connection.execute(
            """
            INSERT INTO rag_corpus_state (corpus, source_path, source_signature)
            VALUES (?, ?, ?)
            ON CONFLICT(corpus, source_path)
            DO UPDATE SET source_signature = excluded.source_signature
            """,
            (corpus, source_path, signature),
        )
        connection.commit()

    def _search_embeddings(
        self,
        connection: sqlite3.Connection,
        *,
        corpus: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievalMatch]:
        rows = connection.execute(
            """
            SELECT
                rag_chunks.chunk_id,
                rag_chunks.file_path,
                rag_chunks.start_line,
                rag_chunks.end_line,
                rag_chunks.content,
                rag_chunks.metadata_json,
                distance
            FROM rag_vectors
            JOIN rag_chunks ON rag_chunks.rowid = rag_vectors.rowid
            WHERE rag_vectors.embedding MATCH ?
              AND k = ?
              AND rag_chunks.corpus = ?
            ORDER BY distance
            """,
            (sqlite_vec.serialize_float32(query_embedding), top_k, corpus),
        ).fetchall()

        matches: list[RetrievalMatch] = []
        for row in rows:
            metadata = json.loads(row[5]) if row[5] else {}
            chunk = RetrievalChunk(
                chunk_id=row[0],
                corpus=corpus,
                file_path=row[1],
                start_line=row[2],
                end_line=row[3],
                content=row[4],
                metadata=metadata,
            )
            distance = float(row[6])
            matches.append(
                RetrievalMatch(
                    chunk=chunk,
                    score=max(0.0, 1.0 - distance),
                    strategy="vector",
                )
            )
        return matches

    def _initialise_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_chunks (
                chunk_id TEXT PRIMARY KEY,
                corpus TEXT NOT NULL,
                source_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_corpus_state (
                corpus TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_signature TEXT NOT NULL,
                PRIMARY KEY (corpus, source_path)
            )
            """
        )
        connection.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS rag_vectors USING vec0(
                embedding FLOAT[{self.settings.rag_embedding_dimension}]
            )
            """
        )
        connection.commit()

    def _database_path(self) -> Path:
        if self.settings.codebase_vector_store_path:
            return Path(self.settings.codebase_vector_store_path)
        return Path(self.settings.rag_database_path)


def _to_float_list(vector: object) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]


def _source_signature(source_path: str, chunks: Iterable[RetrievalChunk]) -> str:
    digest = hashlib.sha256()
    digest.update(source_path.encode("utf-8"))
    for chunk in chunks:
        digest.update(chunk.chunk_id.encode("utf-8"))
        digest.update(chunk.content.encode("utf-8"))
    return digest.hexdigest()


def _load_sqlite_vec(connection: sqlite3.Connection) -> bool:
    if sqlite_vec is None:
        return False
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
    except Exception:
        return False
    return True
