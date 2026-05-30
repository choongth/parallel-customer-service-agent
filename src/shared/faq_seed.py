"""
One-time script to pre-populate the FAQCache DynamoDB table.

Run after deployment:
    FAQ_TABLE=FAQCache python src/shared/faq_seed.py

Why bypass save_faq() here?
    save_faq() uses attribute_not_exists — it refuses to overwrite existing entries.
    That's correct for concurrent workers, but a seed script needs to be re-runnable
    (idempotent), so we call put_item directly with no condition.
"""

import hashlib
import os
import re
import sys

import boto3
from botocore.exceptions import ClientError

FAQ_ENTRIES = [
    {
        "question": "What is your return policy",
        "answer": (
            "You can return any item within 30 days of purchase for a full refund. "
            "Items must be unused and in original packaging. "
            "Start a return at our website under Orders > Return Item."
        ),
    },
    {
        "question": "How do I reset my password",
        "answer": (
            "Go to the login page and click 'Forgot Password'. "
            "Enter your email address and we'll send a reset link within 2 minutes. "
            "Check your spam folder if it doesn't arrive."
        ),
    },
    {
        "question": "How long does shipping take",
        "answer": (
            "Standard shipping takes 5–7 business days. "
            "Express shipping (2 business days) is available at checkout for an additional fee. "
            "Orders placed before 2 PM EST ship the same day."
        ),
    },
    {
        "question": "Do you ship internationally",
        "answer": (
            "Yes, we ship to over 50 countries. "
            "International delivery takes 10–14 business days. "
            "Import duties and taxes are the responsibility of the recipient."
        ),
    },
    {
        "question": "How do I cancel my order",
        "answer": (
            "Orders can be cancelled within 1 hour of placement. "
            "Go to Orders > Cancel Order in your account. "
            "After 1 hour, the order may already be packed — contact support and we'll do our best."
        ),
    },
    {
        "question": "How do I track my order",
        "answer": (
            "Once your order ships, you'll receive an email with a tracking number. "
            "You can also find it under Orders > Track Shipment in your account."
        ),
    },
    {
        "question": "What payment methods do you accept",
        "answer": (
            "We accept Visa, Mastercard, American Express, PayPal, and Apple Pay. "
            "All transactions are encrypted and processed securely."
        ),
    },
    {
        "question": "Is my payment information secure",
        "answer": (
            "Yes. We never store your full card number — payments are processed by "
            "Stripe, which is PCI DSS Level 1 certified. "
            "Your data is encrypted in transit and at rest."
        ),
    },
    {
        "question": "How do I contact support",
        "answer": (
            "You can reach us via this chat, by email at support@example.com, "
            "or by phone at 1-800-555-0100 (Mon–Fri, 9 AM–6 PM EST)."
        ),
    },
    {
        "question": "Do you offer discounts for bulk orders",
        "answer": (
            "Yes! Orders over 50 units qualify for a 10% discount, "
            "and orders over 200 units qualify for 20%. "
            "Contact sales@example.com for a custom quote."
        ),
    },
]


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _question_hash(question: str) -> str:
    return hashlib.md5(_normalize(question).encode()).hexdigest()


def seed(table_name: str) -> None:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    success = 0
    for entry in FAQ_ENTRIES:
        q_hash = _question_hash(entry["question"])
        try:
            # put_item with no condition = upsert (overwrite if exists)
            table.put_item(
                Item={
                    "question_hash": q_hash,
                    "question": entry["question"],
                    "answer": entry["answer"],
                    "hit_count": 0,
                }
            )
            print(f"  ✓  {entry['question']}")
            success += 1
        except ClientError as e:
            print(f"  ✗  {entry['question']} — {e.response['Error']['Code']}")

    print(f"\nSeeded {success}/{len(FAQ_ENTRIES)} entries into '{table_name}'.")


if __name__ == "__main__":
    table_name = os.environ.get("FAQ_TABLE", "FAQCache")
    print(f"Seeding FAQ table: {table_name}\n")
    try:
        seed(table_name)
    except ClientError as e:
        print(f"Fatal: {e.response['Error']['Message']}", file=sys.stderr)
        sys.exit(1)
