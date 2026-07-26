import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from embedding_client import EmbeddingClient, cosine_similarity, local_hash_embed
from knowledge_base import KnowledgeBase
from text_tokenize import expand_search_terms, tokenize_text
from tests.test_knowledge_base import sample_note


class HybridRetrievalTests(unittest.TestCase):
    def test_tokenize_expands_compound_category(self):
        tokens = expand_search_terms(["香港蝴蝶酥伴手礼"])
        self.assertIn("蝴蝶酥", tokens)
        self.assertIn("伴手礼", tokens)
        self.assertTrue(any(tok == "香港" or "香港" in tok for tok in tokens))

    def test_local_embeddings_are_deterministic_and_similar_for_related_text(self):
        a = local_hash_embed("香港蝴蝶酥伴手礼推荐礼盒")
        b = local_hash_embed("香港蝴蝶酥伴手礼推荐礼盒")
        c = local_hash_embed("护肤精华补水面膜测评")
        self.assertEqual(a, b)
        self.assertGreater(cosine_similarity(a, local_hash_embed("蝴蝶酥伴手礼送礼")), 0.05)
        self.assertGreater(
            cosine_similarity(a, local_hash_embed("香港必买蝴蝶酥")),
            cosine_similarity(a, c),
        )

    def test_hybrid_search_fuses_keyword_and_vector(self):
        with tempfile.TemporaryDirectory() as directory:
            client = EmbeddingClient(
                config={
                    "api_key": "",
                    "base_url": "http://localhost",
                    "model": "unused",
                    "role": "embedding",
                }
            )
            knowledge = KnowledgeBase(
                Path(directory) / "knowledge.db",
                embedding_client=client,
            )
            gift = sample_note(
                note_id="gift",
                title="香港必买蝴蝶酥伴手礼清单",
                description="送礼首选手工蝴蝶酥礼盒",
                author="作者A",
                likes=200,
            )
            gift.tags = ["蝴蝶酥", "香港伴手礼"]
            gift.search_keyword = "香港伴手礼"
            skincare = sample_note(
                note_id="skincare",
                title="补水精华实测",
                description="敏感肌护肤日记",
                author="作者B",
                likes=9000,
            )
            skincare.tags = ["护肤", "精华"]
            skincare.search_keyword = "护肤精华"
            cookie = sample_note(
                note_id="cookie",
                title="曲奇测评合集",
                description="牛油曲奇口感对比，适合当手信",
                author="作者C",
                likes=120,
            )
            cookie.tags = ["曲奇", "手信"]
            cookie.search_keyword = "香港曲奇"
            knowledge.import_notes([gift, skincare, cookie])
            notes, meta = knowledge.hybrid_search_with_meta(
                ["香港蝴蝶酥伴手礼"],
                limit=5,
                use_vector=True,
            )
            ids = [item.note_id for item in notes]
            self.assertIn("gift", ids)
            self.assertNotEqual(ids[0], "skincare")
            self.assertEqual(meta["mode"], "hybrid")
            self.assertGreaterEqual(meta["keyword_hits"], 1)
            self.assertGreaterEqual(meta["vector_hits"], 1)
            status = knowledge.status()
            self.assertGreaterEqual(status["embedded_notes"], 1)
            self.assertEqual(status["retrieval_mode"], "hybrid_keyword_vector")

    def test_ensure_embeddings_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            client = EmbeddingClient(
                config={
                    "api_key": "",
                    "base_url": "http://localhost",
                    "model": "unused",
                    "role": "embedding",
                }
            )
            knowledge = KnowledgeBase(
                Path(directory) / "knowledge.db",
                embedding_client=client,
            )
            knowledge.import_notes([sample_note()])
            first = knowledge.ensure_note_embeddings()
            second = knowledge.ensure_note_embeddings()
            self.assertEqual(first["embedded"], 1)
            self.assertEqual(second["embedded"], 0)

    def test_tokenize_text_keeps_domain_words(self):
        tokens = tokenize_text("珍妮曲奇和蝴蝶酥都是香港伴手礼")
        self.assertTrue({"珍妮曲奇", "蝴蝶酥", "香港伴手礼"} & set(tokens))


if __name__ == "__main__":
    unittest.main()
