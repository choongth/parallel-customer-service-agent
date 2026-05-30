"""
Unit tests for src/shared/memory.py.
Run without AWS credentials — all boto3 calls are mocked.

    pip install pytest
    pytest tests/test_memory.py -v
"""

import hashlib
import os
import re
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Inject env vars before importing the module (it reads them at import time)
os.environ.setdefault("CONVERSATIONS_TABLE", "Conversations")
os.environ.setdefault("FAQ_TABLE", "FAQCache")

# Make the shared package importable from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _normalize(text):
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _question_hash(question):
    return hashlib.md5(_normalize(question).encode()).hexdigest()


class TestShortTermMemory(unittest.TestCase):

    def setUp(self):
        # Patch boto3.resource so no real AWS calls are made
        patcher = patch("shared.memory._dynamodb", autospec=True)
        self.mock_dynamo = patcher.start()
        self.addCleanup(patcher.stop)

        self.mock_conv_table = MagicMock()
        self.mock_faq_table = MagicMock()

        patcher2 = patch("shared.memory._conversations", self.mock_conv_table)
        patcher3 = patch("shared.memory._faq_cache", self.mock_faq_table)
        patcher2.start(); patcher3.start()
        self.addCleanup(patcher2.stop); self.addCleanup(patcher3.stop)

    def test_get_conversation_returns_empty_for_new_customer(self):
        from shared.memory import get_conversation
        self.mock_conv_table.get_item.return_value = {}  # no "Item" key = not found

        result = get_conversation("new-customer-123")

        self.assertEqual(result, [])
        self.mock_conv_table.get_item.assert_called_once_with(
            Key={"customer_id": "new-customer-123"}
        )

    def test_get_conversation_returns_stored_messages(self):
        from shared.memory import get_conversation
        stored = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        self.mock_conv_table.get_item.return_value = {
            "Item": {"customer_id": "c1", "messages": stored, "last_updated": 999}
        }

        result = get_conversation("c1")

        self.assertEqual(result, stored)

    def test_save_conversation_writes_correct_item(self):
        from shared.memory import save_conversation
        messages = [{"role": "user", "content": "Help"}]

        before = int(time.time())
        save_conversation("c2", messages)
        after = int(time.time())

        call_args = self.mock_conv_table.put_item.call_args[1]["Item"]
        self.assertEqual(call_args["customer_id"], "c2")
        self.assertEqual(call_args["messages"], messages)
        # TTL should be ~1 day from now
        self.assertGreaterEqual(call_args["last_updated"], before + 86400)
        self.assertLessEqual(call_args["last_updated"], after + 86400)


class TestLongTermMemory(unittest.TestCase):

    def setUp(self):
        self.mock_conv_table = MagicMock()
        self.mock_faq_table = MagicMock()

        patcher2 = patch("shared.memory._conversations", self.mock_conv_table)
        patcher3 = patch("shared.memory._faq_cache", self.mock_faq_table)
        patcher2.start(); patcher3.start()
        self.addCleanup(patcher2.stop); self.addCleanup(patcher3.stop)

    def test_get_faq_returns_none_on_cache_miss(self):
        from shared.memory import get_faq
        self.mock_faq_table.get_item.return_value = {}  # no Item = miss

        result = get_faq("How do I reset my password?")

        self.assertIsNone(result)

    def test_get_faq_returns_answer_and_increments_hit_count(self):
        from shared.memory import get_faq
        self.mock_faq_table.get_item.return_value = {
            "Item": {
                "question_hash": "abc",
                "question": "How do I reset my password",
                "answer": "Click Forgot Password on the login page.",
                "hit_count": 5,
            }
        }

        result = get_faq("How do I reset my password?")

        self.assertEqual(result, "Click Forgot Password on the login page.")
        # hit_count increment must have been called
        self.mock_faq_table.update_item.assert_called_once()
        update_kwargs = self.mock_faq_table.update_item.call_args[1]
        self.assertIn("hit_count = hit_count + :one", update_kwargs["UpdateExpression"])

    def test_get_faq_normalizes_before_hashing(self):
        """Variations of the same question must resolve to the same cache entry."""
        from shared.memory import get_faq
        self.mock_faq_table.get_item.return_value = {}

        get_faq("How do I reset my password?")
        get_faq("how do i reset my password")
        get_faq("HOW DO I RESET MY PASSWORD??!")

        # All three calls should use the identical hash key
        calls = self.mock_faq_table.get_item.call_args_list
        keys = [c[1]["Key"]["question_hash"] for c in calls]
        self.assertEqual(len(set(keys)), 1, "All variants should hash to the same key")

    def test_save_faq_writes_correct_item(self):
        from shared.memory import save_faq
        save_faq("What is your return policy", "30 days, no questions asked.")

        call_args = self.mock_faq_table.put_item.call_args[1]["Item"]
        expected_hash = _question_hash("What is your return policy")
        self.assertEqual(call_args["question_hash"], expected_hash)
        self.assertEqual(call_args["answer"], "30 days, no questions asked.")
        self.assertEqual(call_args["hit_count"], 0)

    def test_save_faq_does_not_raise_on_duplicate(self):
        """ConditionalCheckFailedException from a concurrent worker must be swallowed."""
        from botocore.exceptions import ClientError
        from shared.memory import save_faq

        error = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
            "PutItem",
        )
        self.mock_faq_table.put_item.side_effect = error

        # Should not raise
        save_faq("duplicate question", "some answer")


if __name__ == "__main__":
    unittest.main()
