# 🤖 Parallel Customer Support Agent

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)
![AWS Lambda](https://img.shields.io/badge/AWS_Lambda-Serverless-FF9900?style=flat&logo=awslambda&logoColor=white)
![Amazon SQS](https://img.shields.io/badge/Amazon_SQS-Queue-FF4F8B?style=flat&logo=amazonsqs&logoColor=white)
![Amazon DynamoDB](https://img.shields.io/badge/Amazon_DynamoDB-Database-4053D6?style=flat&logo=amazondynamodb&logoColor=white)
![Amazon API Gateway](https://img.shields.io/badge/Amazon_API_Gateway-REST-FF4F8B?style=flat&logo=amazonapigateway&logoColor=white)
![Amazon Bedrock](https://img.shields.io/badge/Amazon_Bedrock-Claude_3.5-232F3E?style=flat&logo=amazonaws&logoColor=white)
![AWS SAM](https://img.shields.io/badge/AWS_SAM-IaC-FF9900?style=flat&logo=amazonaws&logoColor=white)
![AWS CloudFormation](https://img.shields.io/badge/AWS_CloudFormation-Stack-FF9900?style=flat&logo=amazonaws&logoColor=white)
![AWS IAM](https://img.shields.io/badge/AWS_IAM-Security-DD344C?style=flat&logo=amazonaws&logoColor=white)
![Amazon S3](https://img.shields.io/badge/Amazon_S3-Artifacts-569A31?style=flat&logo=amazons3&logoColor=white)
![CloudWatch](https://img.shields.io/badge/CloudWatch-Observability-FF4F8B?style=flat&logo=amazonaws&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-Testing-0A9EDC?style=flat&logo=pytest&logoColor=white)

</div>

> A serverless, parallel AI customer support system built on AWS. Demonstrates **multi-agent parallelization** via SQS + Lambda and a **two-layer memory system** via DynamoDB — achieving a **9.3× speedup** over sequential processing.

---

## 🏗️ Architecture

```
Customer (HTTP POST)
        │
        ▼
  API Gateway          ← managed HTTP endpoint, no server required
        │
        ▼
 Lambda: Enqueue       ← validates request, pushes to queue, returns 202 immediately
        │
        ▼
   SQS Queue           ← durable message buffer, fans out to N workers in parallel
        │
   ┌────┴────┬─────────┬─────────┐
   ▼         ▼         ▼         ▼
Worker    Worker    Worker    Worker   ← one Lambda per customer, all run simultaneously
   │         │         │         │
   └────┬────┴─────────┘         │
        ▼                        ▼
  Amazon Bedrock            DynamoDB
  (Claude 3.5 Sonnet)    ┌──────────────┐
                         │ Conversations │  ← short-term memory (per customer, TTL 1 day)
                         │ FAQCache      │  ← long-term memory  (shared, persistent)
                         └──────────────┘
```

---

## 💡 Key Concepts

### ⚡ Agent Parallelization
When N customers send messages simultaneously, SQS receives all N messages and AWS automatically invokes N Lambda workers in parallel — no threading code, no server management. The load test proved **9.3× speedup** over sequential processing (10 customers handled in 1 second instead of 9).

### 🧠 Two-Layer Memory System

| Layer | Table | Scope | Lifetime | Key |
|---|---|---|---|---|
| 🔵 Short-term | `Conversations` | Per customer | 1 day (DynamoDB TTL) | `customer_id` |
| 🟢 Long-term | `FAQCache` | All customers | Permanent | MD5 of normalized question |

**🔵 Short-term memory** preserves conversation history across multiple messages. Claude receives the full history on every call, so it remembers what the customer said earlier in the session.

**🟢 Long-term memory** caches answers to general questions. The second customer to ask "What is your return policy?" never reaches Claude — the cached answer is returned in ~175ms instead of ~3–4 seconds.

### 🪣 Dead-Letter Queue (DLQ)
If a worker fails 3 times on the same message (e.g. transient Bedrock error), SQS moves it to `support-queue-dlq` instead of retrying forever. Messages are retained for 14 days for inspection and replay.

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| 🐍 Language | Python 3.11 | Lambda runtime |
| 🤖 AI Model | Claude 3.5 Sonnet (APAC) | Customer support responses |
| ☁️ AI Provider | Amazon Bedrock | Hosted model API, no separate API key needed |
| 📨 Queue | Amazon SQS | Parallelism backbone, decouples producer from workers |
| 🪣 Dead-Letter Queue | Amazon SQS DLQ | Catches messages that fail 3× for inspection/replay |
| ⚡ Compute | AWS Lambda | Serverless worker execution, auto-scales to N workers |
| 🌐 API | Amazon API Gateway | Public HTTP endpoint, routes POST /support to Lambda |
| 🗄️ Database | Amazon DynamoDB | Two-layer agent memory (on-demand, TTL auto-cleanup) |
| 📦 IaC | AWS SAM | Defines all resources in `template.yaml`, transforms to CloudFormation |
| 🔧 Stack Engine | AWS CloudFormation | Underlying engine that creates/updates/deletes all AWS resources |
| 🔐 Permissions | AWS IAM | Lambda execution roles and inline policies (SQS, DynamoDB, Bedrock) |
| 🗃️ Artifact Storage | Amazon S3 | Stores Lambda deployment packages during `sam deploy` (auto-managed by SAM) |
| 📊 Observability | Amazon CloudWatch | Lambda logs, Logs Insights for cross-stream parallel execution queries |
| 🔌 SDK | boto3 | AWS Python SDK — used for SQS, DynamoDB, and Bedrock Converse API |
| 🧪 Testing | pytest | Unit tests for memory layer with mocked boto3 |

---

## 📁 Project Structure

```
parallel-customer-service-agent/
├── template.yaml              # AWS SAM — defines all AWS resources
├── requirements.txt           # Production dependencies (boto3 — packaged into Lambda)
├── requirements-dev.txt       # Dev dependencies (boto3 + pytest — local only)
├── .env.example               # Environment variable reference
├── src/
│   ├── enqueue/
│   │   └── handler.py         # API Gateway → SQS (validate & push)
│   ├── worker/
│   │   └── handler.py         # SQS → Bedrock → DynamoDB (agent core)
│   └── shared/
│       ├── memory.py          # DynamoDB read/write helpers (both memory layers)
│       └── faq_seed.py        # Pre-populate FAQCache with known Q&A
└── tests/
    ├── test_memory.py         # Unit tests for memory.py (mocked DynamoDB)
    └── load_test.py           # Concurrent HTTP test to prove parallelism
```

---

## ✅ Prerequisites

- 🐍 Python 3.10+
- ☁️ [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configured (`aws configure`)
- 📦 [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- 🤖 Amazon Bedrock model access enabled for **APAC Claude 3.5 Sonnet** in your region

---

## 🚀 Setup & Deployment

### 1. 🐍 Create virtual environment

**Windows**
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
```

**macOS/Linux**
```bash
python -m venv .venv
source .venv/bin/activate && pip install -r requirements-dev.txt
```

### 2. ☁️ Deploy to AWS
```bash
sam build && sam deploy --guided
```

Answer the prompts:
| Prompt | Value |
|---|---|
| Stack Name | `parallel-support-agent` |
| AWS Region | your region (e.g. `ap-southeast-1`) |
| Confirm changes | `y` |
| Allow SAM IAM role creation | `y` |
| Disable rollback | `n` |
| API without auth | `y` |
| Save to config file | `y` |

Copy the `ApiEndpoint` and `SupportQueueUrl` from the deploy output into your `.env`.

### 3. 🤖 Enable Bedrock model access
AWS Console → Amazon Bedrock → Model access → Enable **APAC Claude 3.5 Sonnet**

### 4. 🌱 Seed the FAQ knowledge base
```bash
FAQ_TABLE=FAQCache python src/shared/faq_seed.py
```

### 5. 🧪 Run unit tests
```bash
.venv\Scripts\python -m pytest tests/test_memory.py -v
```

---

## 📬 Usage

### Send a support request
```bash
curl -X POST https://<api-id>.execute-api.<region>.amazonaws.com/Prod/support \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "customer-001", "message": "What is your return policy?"}'
```

Response (immediate, async):
```json
{
  "ticket_id": "c1db2bf4-b21e-4d0c-ac51-5e89b3d47fba",
  "status": "queued",
  "message": "Your request is being processed"
}
```

> 💡 Claude's response is written to DynamoDB → `Conversations` table under the customer's `customer_id`.

### ⚡ Run the load test
```bash
python tests/load_test.py --endpoint https://... --customers 10
```

Expected output:
```
Firing 10 concurrent customer requests → https://...

  ✓  customer-54c81d8f  890ms  (HTTP 202)
  ✓  customer-a8cb22f5  888ms  (HTTP 202)
  ...

Customers sent:       10
Successful (202):     10
Wall-clock total:     1009ms
Parallelism speedup:  9.3× faster than sequential
```

---

## 🧠 Memory System — How It Works

```
Incoming message: "What is your return policy?"
        │
        ├─ 🟢 get_faq(message)
        │       └─ MD5("what is your return policy") → look up FAQCache
        │               Hit?  → return cached answer in ~175ms (skip Claude) ✅
        │               Miss? → continue ↓
        │
        ├─ 🔵 get_conversation(customer_id)
        │       └─ load full message history from Conversations table
        │
        ├─ 🤖 bedrock.converse(history + new message)
        │       └─ Claude sees full context → generates reply
        │
        ├─ 🔵 save_conversation(customer_id, updated_history)
        │       └─ append new exchange, reset TTL to +1 day
        │
        └─ 🟢 save_faq(message, reply)   ← only if no digits in message
                └─ cache for future customers
```

---

## 📊 Observability

View worker logs in CloudWatch:
```
AWS Console → Lambda → support-worker → Monitor → View CloudWatch Logs
```

Query parallel execution across all workers (Logs Insights):
```sql
fields @timestamp, @message
| filter @message like "Processing ticket"
| sort @timestamp asc
| limit 50
```

---

## 💰 Cost Estimate (development usage)

| Service | Dev Cost |
|---|---|
| ⚡ Lambda | ~$0.00 (free tier: 1M requests/month) |
| 📨 SQS | ~$0.00 (free tier: 1M requests/month) |
| 🗄️ DynamoDB | ~$0.00 (on-demand, free tier: 25 GB) |
| 🌐 API Gateway | ~$0.00 (free tier: 1M calls/month) |
| 🤖 Amazon Bedrock | ~$0.003 per 1K input tokens (Claude 3.5 Sonnet) |

---

## 🗑️ Cleanup

To tear down all AWS resources:
```bash
sam delete
```
