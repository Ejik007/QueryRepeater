import asyncio
import json
import logging
from leasing_client import LeasingAnalyticsClient, InvalidINNError

logging.basicConfig(level=logging.INFO)


async def run_tests():
    client = LeasingAnalyticsClient()

    print("=== TEST 1: Validation Invalid INN ===")
    try:
        await client.get_leasing_info("12345")
        print("FAIL: Should have raised InvalidINNError")
    except InvalidINNError as e:
        print(f"PASS: Correctly caught invalid INN error -> {e}")

    print("\n=== TEST 2: Valid INN 7707083893 (Сбербанк - 95 contracts) ===")
    try:
        res = await client.get_leasing_info("7707083893")
        print(f"PASS: INN={res['inn']}")
        print(f"Total Contracts: {res['total_contracts']}")
        print(f"Leasing Companies Summary Count: {len(res['summary'])}")
        if res["contracts"]:
            print("Sample Contract 0:")
            print(json.dumps(res["contracts"][0], ensure_ascii=False, indent=2))
        assert res["total_contracts"] > 0, "Expected contracts count > 0"
        print("SUCCESS: Contract count > 0 verified!")
    except Exception as e:
        print(f"FAIL: Error querying INN 7707083893 -> {e}")


if __name__ == "__main__":
    asyncio.run(run_tests())
