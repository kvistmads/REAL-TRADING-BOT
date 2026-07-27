"""ChromaDB-wrapper: gem observationer som embeddings og hent semantisk lignende.

Loopsene bruger den til at give LLM'en historisk kontekst ("har vi set dette
mønster før?"). Tests bruger en in-memory EphemeralClient — ingen disk-writes.
"""

from __future__ import annotations

import logging
from typing import Optional

import chromadb

# Import-stien til DefaultEmbeddingFunction har skiftet mellem chromadb-versioner.
# Prøv den dokumenterede sti først, fald ellers tilbage til den nye placering.
try:  # chromadb >= 0.4
    from chromadb.utils import embedding_functions as _ef_module
except Exception:  # pragma: no cover - afhænger af installeret version
    _ef_module = None

logger = logging.getLogger(__name__)

COLLECTION_NAME = "trading_observations"


def _default_embedding_function():
    """Returnér en DefaultEmbeddingFunction uanset chromadb-version, ellers None.

    None = lad collection'en bruge chromadb's egen default (nyere versioner
    tilføjer selv en embedder hvis ingen angives).
    """
    if _ef_module is not None and hasattr(_ef_module, "DefaultEmbeddingFunction"):
        try:
            return _ef_module.DefaultEmbeddingFunction()
        except Exception as e:  # pragma: no cover
            logger.warning("Kunne ikke initialisere DefaultEmbeddingFunction: %s", e)
    return None


class ObservationStore:
    """Persistent (eller ephemeral) embeddings-store for observationer."""

    def __init__(
        self,
        persist_dir: Optional[str] = "data/chromadb",
        client=None,
        collection_name: str = COLLECTION_NAME,
    ):
        """
        persist_dir: mappe til ChromaDB på disk. Ignoreres hvis ``client`` er givet.
        client: injicér en egen chromadb-client (fx ``chromadb.EphemeralClient()``
                i tests) for at undgå disk-writes. Bemærk at EphemeralClient deler
                state i processen — brug et unikt ``collection_name`` for at isolere.
        collection_name: navn på collection'en (min. 3 tegn).
        """
        if client is not None:
            self.client = client
        else:
            self.client = chromadb.PersistentClient(path=persist_dir)

        self.ef = _default_embedding_function()
        kwargs = {"name": collection_name}
        if self.ef is not None:
            kwargs["embedding_function"] = self.ef
        self.collection = self.client.get_or_create_collection(**kwargs)

    def add(self, obs_id: int, text: str, metadata: dict) -> str:
        """Gem observation som embedding. Returnér ChromaDB-id."""
        chroma_id = f"obs_{obs_id}"
        # ChromaDB tillader kun str/int/float/bool i metadata — sanitér.
        clean = {k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool))}
        self.collection.add(documents=[text], metadatas=[clean or {"_": ""}], ids=[chroma_id])
        return chroma_id

    def query_similar(self, text: str, n: int = 5) -> list[dict]:
        """Hent de N mest semantisk ens historiske observationer.

        Returnerer [] hvis collection'en er tom (ChromaDB fejler ellers på en
        tom query i nogle versioner).
        """
        if self.collection.count() == 0:
            return []
        results = self.collection.query(query_texts=[text], n_results=n)
        docs = results.get("documents") or [[]]
        metas = results.get("metadatas") or [[]]
        return [
            {"text": doc, "metadata": meta or {}}
            for doc, meta in zip(docs[0], metas[0])
        ]
