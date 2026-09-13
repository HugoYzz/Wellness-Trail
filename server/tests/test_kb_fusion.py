import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy.orm import Session

from app import config
from app.database import Base, make_engine
from app.models import KbChunk, KbDoc
from app.services.kb import _rrf_merge
from app.services import vector_kb


class ReciprocalRankFusionTests(unittest.TestCase):
    def test_duplicate_hits_gain_rank_and_keep_sources(self):
        keyword = [
            {"chunk_id": 1, "content": "a", "retrieval": "fts5"},
            {"chunk_id": 2, "content": "b", "retrieval": "fts5"},
        ]
        vector = [
            {"chunk_id": 2, "content": "b", "retrieval": "vector"},
            {"chunk_id": 3, "content": "c", "retrieval": "vector"},
        ]

        result = _rrf_merge([keyword, vector], top=3)

        self.assertEqual(result[0]["chunk_id"], 2)
        self.assertEqual(result[0]["retrieval"], "fts5+vector")
        self.assertEqual({item["chunk_id"] for item in result}, {1, 2, 3})


class LocalVectorStoreTests(unittest.TestCase):
    def test_rebuild_and_query_local_qdrant(self):
        def fake_embed(texts):
            return [[1.0, 0.0] if "运动" in text else [0.0, 1.0] for text in texts]

        with TemporaryDirectory() as tmp_dir:
            engine = make_engine(Path(tmp_dir) / "test.sqlite3")
            try:
                Base.metadata.create_all(engine)
                with Session(engine) as db:
                    doc = KbDoc(title="测试", source_plan="august_fatloss", version="1")
                    db.add(doc)
                    db.flush()
                    db.add_all(
                        [
                            KbChunk(
                                doc_id=doc.id,
                                title="测试",
                                heading="运动",
                                source_plan="august_fatloss",
                                section_no="1",
                                content="运动后注意补水",
                            ),
                            KbChunk(
                                doc_id=doc.id,
                                title="测试",
                                heading="睡眠",
                                source_plan="august_fatloss",
                                section_no="2",
                                content="保持规律睡眠",
                            ),
                        ]
                    )
                    db.commit()

                    with (
                        patch.object(config, "RAG_VECTOR_ENABLED", True),
                        patch.object(config, "RAG_VECTOR_PATH", str(Path(tmp_dir) / "qdrant")),
                        patch.object(vector_kb, "_embed", side_effect=fake_embed),
                    ):
                        rebuilt = vector_kb.rebuild(db)
                        hits = vector_kb.search("运动", top=1)

                    self.assertTrue(rebuilt["ready"])
                    self.assertEqual(rebuilt["indexed"], 2)
                    self.assertEqual(hits[0]["heading"], "运动")
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
