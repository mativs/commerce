def run_check(client, code: str, key: str = "validation", **body):
    response = client.post(
        "/order-validation-runs",
        json={"checks": [code], **body},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "COMPLETED", result
    assert all(check["status"] == "COMPLETED" for check in result["checks"]), result
    findings = client.get(f"/order-validation-runs/{result['id']}/findings").json()
    return result, findings
