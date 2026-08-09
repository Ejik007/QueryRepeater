from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    print("Health response:", response.json())
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_canary_health():
    response = client.get("/health/canary")
    print("Canary health response:", response.json())
    assert response.status_code == 200
    data = response.json()
    assert data["canary_status"] == "ok"
    assert data["contracts_found"] > 0
    print("PASS: Canary self-test verified!")


def test_invalid_inn():
    response = client.get("/api/v1/leasing/123")
    print("Invalid INN status:", response.status_code, response.json())
    assert response.status_code == 400


def test_valid_inn_endpoint():
    response = client.get("/api/v1/leasing/7707083893")
    print("Valid INN endpoint status:", response.status_code)
    data = response.json()
    print("INN:", data["inn"])
    print("Total contracts:", data["total_contracts"])
    assert response.status_code == 200
    assert data["total_contracts"] == 95
    print("API TEST PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    test_health()
    test_canary_health()
    test_invalid_inn()
    test_valid_inn_endpoint()
