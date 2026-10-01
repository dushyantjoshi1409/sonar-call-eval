from __future__ import annotations

from fastapi.testclient import TestClient

from voice_eval.regression import REGRESSION_SUITE_VERSION, regression_cases


def test_fixed_suite_has_authored_snapshots_and_expectations() -> None:
    cases = regression_cases()
    assert REGRESSION_SUITE_VERSION == "voice-eval-regression-v1"
    assert {case.category for case in cases} >= {
        "dental",
        "delivery",
        "meaning-negation",
        "repetition",
        "flow",
    }
    assert all(case.synthetic for case in cases)
    assert all(len(case.profile_hash) == 64 for case in cases)
    assert all(
        set(case.expectations)
        == {"semantic_uptake", "unnecessary_repetition", "scenario_flow", "response_length"}
        for case in cases
    )


def test_no_key_regression_run_keeps_semantics_unknown_and_persists_metadata(
    client: TestClient,
) -> None:
    created = client.post("/api/regression-runs", json={})
    assert created.status_code == 201
    run = created.json()
    assert run["suite_version"] == REGRESSION_SUITE_VERSION
    assert run["provider"] == "offline"
    assert run["prompt_version"]
    assert run["rubric_version"]
    assert run["synthetic"] is True
    assert all(
        check["actual"] == "UNKNOWN" and check["comparison"] == "unresolved"
        for case in run["cases"]
        for check in case["checks"]
        if check["metric_id"] != "response_length"
    )
    listed = client.get("/api/regression-runs")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == run["id"]


def test_baseline_comparison_requires_compatible_versions(client: TestClient) -> None:
    baseline = client.post("/api/regression-runs", json={}).json()
    compared = client.post("/api/regression-runs", json={"baseline_id": baseline["id"]})
    assert compared.status_code == 201
    assert compared.json()["baseline_id"] == baseline["id"]
    assert all(
        check["comparison"] in {"unchanged", "unresolved"}
        for case in compared.json()["cases"]
        for check in case["checks"]
    )

    incompatible = {**baseline, "id": "incompatible-baseline", "suite_version": "legacy"}
    client.app.state.runtime.store.save_regression_run(incompatible)
    rejected = client.post("/api/regression-runs", json={"baseline_id": incompatible["id"]})
    assert rejected.status_code == 422
    assert "incompatible" in rejected.json()["detail"]


def test_regression_page_labels_synthetic_cases_and_no_aggregate(client: TestClient) -> None:
    page = client.get("/regression")
    assert page.status_code == 200
    assert "Synthetic regression checks" in page.text
    assert "not measured live-agent accuracy" in page.text
    assert "No weighted aggregate" in page.text
    assert "Expected PASS" in page.text
    assert "Expected FAIL" in page.text
