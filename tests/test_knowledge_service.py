from __future__ import annotations

import unittest

import knowledge_service


class KnowledgeServiceTests(unittest.TestCase):
    def test_status_loads_deployment_bundle(self):
        status = knowledge_service.get_knowledge_status()
        self.assertTrue(status["available"], status.get("error"))
        self.assertEqual(status["counts"]["documents"], 334)
        self.assertEqual(status["counts"]["chunks"], 7458)
        self.assertEqual(status["counts"]["claims"], 1134)
        self.assertEqual(status["counts"]["decisions"], 0)

    def test_search_returns_traceable_sources(self):
        result = knowledge_service.search_knowledge("投产低怎么调整", limit=5)
        self.assertGreater(result["count"], 0)
        self.assertTrue(all(item["source_path"] for item in result["results"]))
        self.assertTrue(all(item["decision_enabled"] is False for item in result["results"]))

    def test_decision_search_stays_empty(self):
        result = knowledge_service.search_knowledge("投产", decision_only=True, limit=5)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["message"], knowledge_service.NO_VERIFIED_KNOWLEDGE)

    def test_assist_has_retrieval_fallback(self):
        result = knowledge_service.answer_with_knowledge(
            "新品冷启动怎么判断", use_ai=False, limit=4
        )
        self.assertEqual(result["answer_source"], "retrieval")
        self.assertGreater(result["count"], 0)
        self.assertIn("参考资料", result["answer"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
