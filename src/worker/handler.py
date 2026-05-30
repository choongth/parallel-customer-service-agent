import json
import logging
import os
import re

import boto3
from botocore.exceptions import ClientError

from shared.memory import get_conversation, get_faq, save_conversation, save_faq

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level Bedrock client — reused across warm Lambda invocations
_bedrock = boto3.client("bedrock-runtime")
_MODEL_ID = os.environ["BEDROCK_MODEL_ID"]

_SYSTEM_PROMPT = (
    "You are a helpful customer support agent. "
    "Be concise, friendly, and solution-focused. "
    "If you cannot resolve an issue, clearly explain the next step the customer should take."
)


def lambda_handler(event: dict, context) -> None:
    """
    SQS → Claude (Bedrock) → DynamoDB worker.

    SQS passes a list of records. BatchSize=1 means exactly one record per invocation.
    Returning normally tells SQS to delete the message (success).
    Raising an exception tells SQS to retry (up to maxReceiveCount times, then DLQ).
    """
    record = event["Records"][0]
    payload = json.loads(record["body"])

    ticket_id = payload["ticket_id"]
    customer_id = payload["customer_id"]
    message = payload["message"]

    logger.info("Processing ticket %s", ticket_id)

    # ── 1. Check long-term memory (FAQ cache) ────────────────────────────────
    # If this question (or one semantically identical after normalization) was
    # answered before, skip Claude entirely and return the cached answer.
    cached_answer = get_faq(message)
    if cached_answer:
        logger.info("FAQ cache hit — skipping Bedrock for ticket %s", ticket_id)
        _append_and_save(customer_id, message, cached_answer)
        return  # SQS deletes the message on normal return

    # ── 2. Load short-term memory (conversation history) ─────────────────────
    # History is stored flat: [{"role": "user", "content": "..."}, ...]
    # We need to convert to Bedrock's format: content must be a list of blocks
    history = get_conversation(customer_id)
    bedrock_messages = _to_bedrock_format(history)

    # Append the new incoming message at the end of the history
    bedrock_messages.append({"role": "user", "content": [{"text": message}]})

    # ── 3. Call Claude via Bedrock ────────────────────────────────────────────
    reply = _invoke_claude(bedrock_messages)

    # ── 4. Persist updated conversation (short-term memory write) ─────────────
    _append_and_save(customer_id, message, reply, existing_history=history)

    # ── 5. Cache in FAQ if this looks like a general question ─────────────────
    # General questions have no digits (no order #s, account #s, tracking #s).
    # These are worth caching because other customers will ask the same thing.
    if _is_general_question(message):
        save_faq(message, reply)

    logger.info("Completed ticket %s", ticket_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke_claude(messages: list[dict]) -> str:
    """
    Call Claude on Bedrock using the converse() API.

    converse() is the higher-level Bedrock API — it handles JSON encoding and
    works identically across Claude model versions, unlike invoke_model() which
    requires model-specific request bodies.
    """
    try:
        response = _bedrock.converse(
            modelId=_MODEL_ID,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=messages,
            inferenceConfig={
                "maxTokens": 512,
                "temperature": 0.3,   # lower = more consistent support responses
            },
        )
        return response["output"]["message"]["content"][0]["text"]
    except ClientError as e:
        logger.error("Bedrock converse failed: %s", e.response["Error"]["Code"])
        raise  # bubble up so SQS retries this message


def _to_bedrock_format(stored_messages: list[dict]) -> list[dict]:
    """
    Convert flat storage format → Bedrock converse() message format.

    Stored:  {"role": "user", "content": "Hello"}
    Bedrock: {"role": "user", "content": [{"text": "Hello"}]}

    Bedrock requires content to be a list of typed content blocks.
    We store flat strings in DynamoDB to keep storage simple.
    """
    return [
        {"role": m["role"], "content": [{"text": m["content"]}]}
        for m in stored_messages
    ]


def _append_and_save(
    customer_id: str,
    user_message: str,
    assistant_reply: str,
    existing_history: list[dict] | None = None,
) -> None:
    """Append the new exchange to history and persist it."""
    history = existing_history or get_conversation(customer_id)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_reply})
    save_conversation(customer_id, history)


def _is_general_question(message: str) -> bool:
    """
    Heuristic: a message with no digits is unlikely to reference a specific
    order, account, or tracking number — making it a good FAQ candidate.
    """
    return not re.search(r"\d", message)
