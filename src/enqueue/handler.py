import json
import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level client — reused across warm Lambda invocations
_sqs = boto3.client("sqs")
_QUEUE_URL = os.environ["SQS_QUEUE_URL"]


def lambda_handler(event: dict, context) -> dict:
    """
    API Gateway → SQS enqueue.

    Expects POST body: {"customer_id": "...", "message": "..."}
    Returns 202 immediately — processing happens asynchronously in the worker.
    """
    # ── 1. Parse body ────────────────────────────────────────────────────────
    # API Gateway passes the HTTP body as a raw string, never parsed JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Request body must be valid JSON"})

    # ── 2. Validate required fields ──────────────────────────────────────────
    customer_id = body.get("customer_id", "").strip()
    message = body.get("message", "").strip()

    if not customer_id:
        return _response(400, {"error": "customer_id is required"})
    if not message:
        return _response(400, {"error": "message is required"})
    if len(message) > 2000:
        return _response(400, {"error": "message exceeds 2000 character limit"})

    # ── 3. Push to SQS ───────────────────────────────────────────────────────
    # MessageGroupId is not needed here (standard queue, not FIFO).
    # Each SendMessage call produces exactly one SQS message → one worker Lambda.
    ticket_id = str(uuid.uuid4())
    payload = {
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "message": message,
    }

    try:
        _sqs.send_message(
            QueueUrl=_QUEUE_URL,
            MessageBody=json.dumps(payload),
        )
    except ClientError as e:
        logger.error("SQS send failed: %s", e.response["Error"]["Code"])
        return _response(503, {"error": "Failed to queue message, please retry"})

    logger.info("Queued ticket %s for customer %s", ticket_id, customer_id)

    # ── 4. Return 202 immediately ─────────────────────────────────────────────
    # 202 Accepted = "I received your request; it is being processed"
    # The customer does not wait for Claude — they poll or get notified later
    return _response(202, {
        "ticket_id": ticket_id,
        "status": "queued",
        "message": "Your request is being processed",
    })


def _response(status_code: int, body: dict) -> dict:
    """All Lambda responses to API Gateway must follow this exact shape."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
