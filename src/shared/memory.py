import hashlib
import logging
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DynamoDB resource - module-level so Lambda reuses it across warm invocations
# ---------------------------------------------------------------------------
_dynamodb = boto3.resource("dynamodb")
_conversations = _dynamodb.Table(os.environ["CONVERSATIONS_TABLE"])
_faq_cache = _dynamodb.Table(os.environ["FAQ_TABLE"])

TTL_SECONDS = 86400  # 1 day


# ===========================================================================
# SHORT-TERM MEMORY  —  per-customer conversation history
# ===========================================================================

def get_conversation(customer_id: str) -> list[dict]:
    """
    Load the message history for a customer.

    Returns a list of {"role": "user"|"assistant", "content": "..."} dicts
    ready to pass directly into the Bedrock converse() messages parameter.
    Returns [] for a brand-new customer.
    """
    try:
        response = _conversations.get_item(Key={"customer_id": customer_id})
        item = response.get("Item")
        if not item:
            return []
        return item.get("messages", [])
    except ClientError as e:
        logger.error("get_conversation failed: %s", e.response["Error"]["Code"])
        return []


def save_conversation(customer_id: str, messages: list[dict]) -> None:
    """
    Persist the full message list for a customer.

    last_updated is stored as (now + TTL_SECONDS) so DynamoDB auto-deletes
    the row after 1 day of inactivity — no cleanup job needed.
    """
    expiry = int(time.time()) + TTL_SECONDS
    try:
        _conversations.put_item(
            Item={
                "customer_id": customer_id,
                "messages": messages,
                # DynamoDB TTL reads this field; when clock passes this value the row vanishes
                "last_updated": expiry,
            }
        )
    except ClientError as e:
        logger.error("save_conversation failed: %s", e.response["Error"]["Code"])
        raise


# ===========================================================================
# LONG-TERM MEMORY  —  shared FAQ cache across all customers
# ===========================================================================

def _normalize(text: str) -> str:
    """Lowercase and strip punctuation so minor variations hit the same cache entry."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _question_hash(question: str) -> str:
    """MD5 of the normalized question — used as the DynamoDB partition key."""
    return hashlib.md5(_normalize(question).encode()).hexdigest()


def get_faq(question: str) -> str | None:
    """
    Look up a cached answer for this question.

    On a cache hit, increment hit_count (so we can see which FAQs are popular)
    and return the cached answer string.
    Returns None on a cache miss — caller must invoke Claude.
    """
    q_hash = _question_hash(question)
    try:
        response = _faq_cache.get_item(Key={"question_hash": q_hash})
        item = response.get("Item")
        if not item:
            return None

        # Increment hit_count atomically — safe under concurrent Lambda workers
        _faq_cache.update_item(
            Key={"question_hash": q_hash},
            UpdateExpression="SET hit_count = hit_count + :one",
            ExpressionAttributeValues={":one": 1},
        )
        return item["answer"]
    except ClientError as e:
        logger.error("get_faq failed: %s", e.response["Error"]["Code"])
        return None


def save_faq(question: str, answer: str) -> None:
    """
    Cache a newly generated answer so future customers skip the Claude call.

    Uses condition_expression to avoid overwriting an entry that another
    concurrent worker already saved between our cache-miss check and now.
    """
    q_hash = _question_hash(question)
    try:
        _faq_cache.put_item(
            Item={
                "question_hash": q_hash,
                "question": question,
                "answer": answer,
                "hit_count": 0,
            },
            ConditionExpression="attribute_not_exists(question_hash)",
        )
    except ClientError as e:
        # ConditionalCheckFailedException means another worker already saved it — that's fine
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            logger.error("save_faq failed: %s", e.response["Error"]["Code"])
            raise
