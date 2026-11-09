"""Retrieval Evaluation Script measuring Recall@K, Precision@K, Hit Rate, and Exact Match Rate."""

import sys
from typing import Any
from app.services.price_service import PriceService

# Ensure stdout encodes Thai text properly on Windows
sys.stdout.reconfigure(encoding="utf-8")


# Ground truth test query benchmark dataset mapped to actual SQLite Price IDs
BENCHMARK_QUERIES: list[dict[str, Any]] = [
    {
        "query": "เหล็ก DB12 ราคาเท่าไร",
        "record_type": "material",
        "expected_ids": ["MAT-008"],
        "description": "Specific rebar diameter with conversational question",
    },
    {
        "query": "ราคาเหล็กข้ออ้อย",
        "record_type": "material",
        "expected_ids": ["MAT-008", "MAT-009", "MAT-010"],
        "description": "Rebar family query (multiple specifications valid)",
    },
    {
        "query": "ราคาเหล็กทำปลอกเสา",
        "record_type": "material",
        "expected_ids": ["MAT-011"],
        "description": "Functional usage intent (stirrup rebar RB6)",
    },
    {
        "query": "ปูนซีเมนต์ 1 ถุงราคาเท่าไร",
        "record_type": "material",
        "expected_ids": ["MAT-001", "MAT-002"],
        "description": "Cement by bag measurement unit",
    },
    {
        "query": "ค่าแรงก่ออิฐราคาเท่าไร",
        "record_type": "labor",
        "expected_ids": ["LAB-001"],
        "description": "Labor rate for brick masonry",
    },
    {
        "query": "ขอราคาวัสดุประเภทคอนกรีต",
        "record_type": "material",
        "expected_ids": ["MAT-014", "MAT-015"],
        "description": "Concrete material category query",
    },
    {
        "query": "เหล็กข้ออ่อย DB12",
        "record_type": "material",
        "expected_ids": ["MAT-008"],
        "description": "Thai typo approximation query",
    },
    {
        "query": "ปูนซีเมนต์ปอร์ตแลนด์ ประเภทที่ 1",
        "record_type": "material",
        "expected_ids": ["MAT-002"],
        "description": "Full formal material name match",
    },
    {
        "query": "ค่าแรงฉาบปูน",
        "record_type": "labor",
        "expected_ids": ["LAB-002"],
        "description": "Labor rate for plastering",
    },
    {
        "query": "กระเบื้องเซรามิกปูพื้น",
        "record_type": "material",
        "expected_ids": ["MAT-019"],
        "description": "Ceramic floor tile query",
    },
    {
        "query": "อิฐมอญ แดง",
        "record_type": "material",
        "expected_ids": ["MAT-016"],
        "description": "Clay brick synonym match",
    },
    {
        "query": "คอนกรีตผสมเสร็จ กำลังอัด 280 ksc",
        "record_type": "material",
        "expected_ids": ["MAT-015"],
        "description": "Concrete compressive strength specification match",
    },
    {
        "query": "วัสดุที่ไม่มีในระบบและไม่มีข้อมูลราคาแน่นอน_xyz999",
        "record_type": "material",
        "expected_ids": [],
        "description": "Out-of-domain negative test query",
    },
]


def run_evaluation(k_values: list[int] = [1, 3, 5]) -> dict[str, Any]:
    """Run evaluation benchmark across test queries and compute metrics."""
    svc = PriceService()

    total_valid_queries = 0
    total_negative_queries = 0
    negative_handled_correctly = 0
    exact_matches_count = 0

    hits_at_k: dict[int, int] = {k: 0 for k in k_values}
    precision_at_k_sum: dict[int, float] = {k: 0.0 for k in k_values}
    recall_at_k_sum: dict[int, float] = {k: 0.0 for k in k_values}

    print("=" * 80)
    print("CONSTRUCTION PRICE RAG RETRIEVAL BENCHMARK EVALUATION")
    print("=" * 80)

    for item in BENCHMARK_QUERIES:
        q = item["query"]
        expected = set(item["expected_ids"])
        rec_type = item.get("record_type", "material")

        res = svc.search_prices(query=q, record_type=rec_type, max_results=max(k_values))
        retrieved = res.get("results", [])
        retrieved_ids = [r["price_id"] for r in retrieved]

        is_negative = len(expected) == 0

        if is_negative:
            total_negative_queries += 1
            if len(retrieved) == 0 or res.get("status") == "no_results":
                negative_handled_correctly += 1
                status_str = "PASS (Correctly returned empty)"
            else:
                status_str = f"FAIL (Returned {len(retrieved)} ungrounded items)"
            print(f"Query: '{q[:35]}' -> {status_str}")
            continue

        total_valid_queries += 1
        first_method = retrieved[0]["retrieval_method"] if retrieved else "none"
        if first_method == "exact":
            exact_matches_count += 1

        # Check Hit, Precision, Recall at each K
        for k in k_values:
            top_k_ids = set(retrieved_ids[:k])
            overlap = expected & top_k_ids

            if overlap:
                hits_at_k[k] += 1

            precision_at_k_sum[k] += len(overlap) / min(k, len(retrieved_ids)) if retrieved_ids else 0.0
            recall_at_k_sum[k] += len(overlap) / len(expected) if expected else 0.0

        hit1_str = "HIT" if retrieved_ids and retrieved_ids[0] in expected else "MISS"
        top1_name = retrieved[0]["item_name"] if retrieved else "None"
        print(f"[{hit1_str}] '{q}'")
        print(f"      Expected: {list(expected)} | Top 1: [{retrieved_ids[0] if retrieved_ids else 'N/A'}] {top1_name[:35]} (Method: {first_method})")

    # Aggregate Metrics
    hit_rate_at_k = {k: hits_at_k[k] / total_valid_queries for k in k_values}
    mean_precision_at_k = {k: precision_at_k_sum[k] / total_valid_queries for k in k_values}
    mean_recall_at_k = {k: recall_at_k_sum[k] / total_valid_queries for k in k_values}
    exact_match_rate = exact_matches_count / total_valid_queries
    negative_accuracy = negative_handled_correctly / total_negative_queries if total_negative_queries else 1.0

    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY METRICS")
    print("=" * 80)
    print(f"Total Valid Benchmark Queries:    {total_valid_queries}")
    print(f"Total Negative/Invalid Queries:   {total_negative_queries}")
    print(f"Negative Handling Accuracy:       {negative_accuracy * 100:.1f}%")
    print(f"Exact Match Rate:                 {exact_match_rate * 100:.1f}%")
    print("-" * 80)
    for k in k_values:
        print(f"Hit Rate@{k}:                     {hit_rate_at_k[k] * 100:.1f}%")
        print(f"Precision@{k}:                    {mean_precision_at_k[k] * 100:.1f}%")
        print(f"Recall@{k}:                       {mean_recall_at_k[k] * 100:.1f}%")
    print("=" * 80)

    return {
        "total_queries": len(BENCHMARK_QUERIES),
        "valid_queries": total_valid_queries,
        "hit_rate_at_k": hit_rate_at_k,
        "precision_at_k": mean_precision_at_k,
        "recall_at_k": mean_recall_at_k,
        "exact_match_rate": exact_match_rate,
        "negative_accuracy": negative_accuracy,
    }


if __name__ == "__main__":
    run_evaluation()
