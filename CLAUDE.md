# Parallel Customer Support Agent System

## Project Goal
Build a serverless, parallel AI customer support system on AWS.
Demonstrates: multi-agent parallelization via SQS + Lambda,
two-layer memory system via DynamoDB.

## Architecture

```
API Gateway → Lambda (Enqueue) → SQS → Lambda Workers (N parallel) → DynamoDB
↕
Anthropic API (Claude)
```

## Tech Stack
- Runtime: Python 3.11
- AWS: API Gateway, Lambda, SQS, DynamoDB
- AI: Anthropic Python SDK (claude-sonnet-4-20250514)
- IaC: AWS SAM (template.yaml)
- Local dev: AWS SAM CLI + LocalStack (optional)

## Memory System Design
### Layer 1 - Short-term (Conversation Context)
- Table: `Conversations`
- Key: `customer_id` (String)
- Fields: `messages` (List), `last_updated` (Number/Unix timestamp)
- TTL: 86400 seconds (1 day) on `last_updated` field

### Layer 2 - Long-term (FAQ Knowledge Base)
- Table: `FAQCache`
- Key: `question_hash` (String, MD5 of normalized question)
- Fields: `question` (String), `answer` (String), `hit_count` (Number)
- No TTL (persistent)

## Project Structure

```
parallel-support-agent/
├── CLAUDE.md
├── template.yaml          # AWS SAM template
├── requirements.txt
├── src/
│   ├── enqueue/
│   │   └── handler.py     # API Gateway → SQS
│   ├── worker/
│   │   └── handler.py     # SQS → Claude API → DynamoDB
│   └── shared/
│       ├── memory.py      # DynamoDB read/write helpers
│       └── faq_seed.py    # Seed FAQ data
├── tests/
│   ├── test_memory.py
│   └── load_test.py       # Simulate N concurrent customers
└── scripts/
└── deploy.sh
```

## Coding Conventions
- All Lambda handlers follow signature: `lambda_handler(event, context) -> dict`
- Always return `{'statusCode': int, 'body': json.dumps(...)}`
- Use structured logging: `logger = logging.getLogger(__name__)`
- Environment variables (never hardcode): `CONVERSATIONS_TABLE`, `FAQ_TABLE`, `SQS_QUEUE_URL`
- Error handling: catch `ClientError` from boto3, `APIError` from anthropic

## Key Constraints
- Lambda timeout: 30s (Claude API call must complete within this)
- SQS batch size: 1 (one customer message per worker invocation)
- DynamoDB: on-demand capacity (no provisioned throughput needed for dev)
- Never log customer message content (privacy)

## Status: Complete and Deployed

All phases built and deployed to AWS (ap-southeast-1):
1. template.yaml — SAM infrastructure (Lambda, SQS, DynamoDB, API Gateway, Bedrock IAM)
2. src/shared/memory.py — DynamoDB helpers for both memory layers
3. src/enqueue/handler.py — API Gateway → SQS handler
4. src/worker/handler.py — Agent core: Bedrock converse() via boto3, two-layer memory
5. src/shared/faq_seed.py — 10 pre-seeded FAQ entries
6. tests/load_test.py — concurrent load test (proved 9.3× parallelism speedup)
7. tests/test_memory.py — unit tests for memory.py (8/8 passing, mocked DynamoDB)

## Key Decisions Made During Build
- Switched from Anthropic SDK to Amazon Bedrock (boto3) — no separate API key needed
- Model: `apac.anthropic.claude-3-5-sonnet-20240620-v1:0` (APAC cross-region inference)
- CodeUri set to `src/` (not per-function subfolder) so `shared/` is importable by both Lambdas
- Bedrock IAM policy uses `Resource: "*"` for dev (covers both foundation-model and inference-profile ARN types)
- Both Lambda handlers use `src/` CodeUri with full dotted handler path (e.g. `worker.handler.lambda_handler`)