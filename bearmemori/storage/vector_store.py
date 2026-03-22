import chromadb
from chromadb.utils import embedding_functions

from bearmemori.storage.models import MemoryRecord


class VectorStore:
    def __init__(self, persist_dir: str | None = None, embedding_model: str = "all-mpnet-base-v2"):
        self._persist_dir = persist_dir
        self._embedding_model = embedding_model
        self._collection = None

    def init(self) -> None:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self._embedding_model
        )
        if self._persist_dir:
            client = chromadb.PersistentClient(path=self._persist_dir)
        else:
            client = chromadb.EphemeralClient()
        self._collection = client.get_or_create_collection(
            name="memories",
            embedding_function=ef,
        )

    def add(self, record: MemoryRecord) -> None:
        text = f"{record.title}: {record.content}"
        metadata = {
            "category": record.category.value,
            "created_at": record.created_at.isoformat(),
        }
        if record.event_fields:
            metadata["event_datetime"] = record.event_fields.datetime
        self._collection.upsert(
            ids=[record.id],
            documents=[text],
            metadatas=[metadata],
        )

    def delete(self, record_id: str) -> None:
        self._collection.delete(ids=[record_id])

    def update(self, record: MemoryRecord) -> None:
        self.add(record)

    def delete_many(self, record_ids: list[str]) -> None:
        if record_ids:
            self._collection.delete(ids=record_ids)

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict]:
        where = None
        if category:
            where = {"category": category}

        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
        )

        items = []
        if results["ids"] and results["ids"][0]:
            for i, id_ in enumerate(results["ids"][0]):
                items.append(
                    {
                        "id": id_,
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i]
                        if results.get("distances")
                        else None,
                    }
                )
        return items
