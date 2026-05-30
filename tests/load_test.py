"""
Load test: simulate N concurrent customers to prove SQS + Lambda parallelism.

Usage:
    python tests/load_test.py --endpoint https://<api-id>.execute-api.<region>.amazonaws.com/Prod/support
    python tests/load_test.py --endpoint https://... --customers 20

What this proves:
    If workers were sequential: total_time ≈ N × per_request_time
    If truly parallel:          total_time ≈ 1 × per_request_time  (all workers run at once)
"""

import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import urllib.request
import urllib.error

# Realistic customer questions — mix of FAQ hits and novel questions
QUESTIONS = [
    "What is your return policy?",
    "How do I reset my password?",
    "How long does shipping take?",
    "My package arrived damaged, what should I do?",
    "Do you offer student discounts?",
    "How do I cancel my subscription?",
    "What payment methods do you accept?",
    "Can I change my shipping address after ordering?",
    "Do you ship internationally?",
    "How do I contact support?",
    "Is my payment information secure?",
    "What happens if I miss a delivery?",
    "Can I return a digital product?",
    "How do I update my billing information?",
    "Do you offer gift wrapping?",
    "What is your privacy policy?",
    "How do I leave a product review?",
    "Can I use multiple discount codes?",
    "What is your price match guarantee?",
    "How do I apply for a refund?",
]


def send_request(endpoint: str, customer_id: str, message: str) -> dict:
    """Send a single support request and return timing + result."""
    payload = json.dumps({
        "customer_id": customer_id,
        "message": message,
    }).encode()

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = time.perf_counter() - start
            body = json.loads(resp.read())
            return {
                "customer_id": customer_id,
                "status_code": resp.status,
                "ticket_id": body.get("ticket_id"),
                "elapsed_ms": round(elapsed * 1000),
                "success": True,
            }
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - start
        return {
            "customer_id": customer_id,
            "status_code": e.code,
            "elapsed_ms": round(elapsed * 1000),
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "customer_id": customer_id,
            "elapsed_ms": round(elapsed * 1000),
            "success": False,
            "error": str(e),
        }


def run_load_test(endpoint: str, num_customers: int) -> None:
    print(f"\nFiring {num_customers} concurrent customer requests → {endpoint}\n")

    # Build one task per simulated customer
    # Each customer gets a unique ID so conversations stay separate in DynamoDB
    tasks = [
        (f"customer-{uuid.uuid4().hex[:8]}", QUESTIONS[i % len(QUESTIONS)])
        for i in range(num_customers)
    ]

    results = []
    wall_start = time.perf_counter()

    # ThreadPoolExecutor fires all requests at the same moment.
    # max_workers=num_customers ensures no request waits for a thread slot.
    with ThreadPoolExecutor(max_workers=num_customers) as executor:
        futures = {
            executor.submit(send_request, endpoint, cid, msg): cid
            for cid, msg in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = "✓" if result["success"] else "✗"
            print(f"  {status}  {result['customer_id']}  {result['elapsed_ms']}ms  "
                  f"(HTTP {result.get('status_code', '?')})")

    wall_elapsed = time.perf_counter() - wall_start

    # ── Report ────────────────────────────────────────────────────────────────
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    times = [r["elapsed_ms"] for r in successful]

    print(f"\n{'─' * 50}")
    print(f"  Customers sent:      {num_customers}")
    print(f"  Successful (202):    {len(successful)}")
    print(f"  Failed:              {len(failed)}")

    if times:
        avg = sum(times) / len(times)
        print(f"  Avg enqueue time:    {avg:.0f}ms")
        print(f"  Min / Max:           {min(times)}ms / {max(times)}ms")

    print(f"  Wall-clock total:    {wall_elapsed * 1000:.0f}ms")

    if len(successful) == num_customers:
        # Parallelism check: if all N requests fit inside ~2× the avg single request time,
        # the enqueue Lambdas ran in parallel (wall time ≈ single request, not N × single)
        sequential_estimate = avg * num_customers
        speedup = sequential_estimate / (wall_elapsed * 1000)
        print(f"  Parallelism speedup: {speedup:.1f}× faster than sequential")
        print(f"  (sequential would have taken ~{sequential_estimate:.0f}ms)")

    print(f"{'─' * 50}\n")

    if failed:
        print("Failed requests:")
        for r in failed:
            print(f"  {r['customer_id']}: {r.get('error', 'unknown')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parallel customer support load test")
    parser.add_argument(
        "--endpoint",
        required=True,
        help="API Gateway endpoint URL (from SAM deploy Outputs)",
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=10,
        help="Number of concurrent customers to simulate (default: 10)",
    )
    args = parser.parse_args()
    run_load_test(args.endpoint, args.customers)
