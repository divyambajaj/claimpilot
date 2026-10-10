"""End to end over HTTP in replay mode: gallery upload -> questions -> answers -> ready -> submit."""

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import Container
from tests.integration.conftest import wait_processed

GALLERY = [
    "restaurant_chaiwala_mumbai",
    "hotel_harbourview_bengaluru",
    "upi_paynow_harbourview",
    "ride_rydego_pune",
    "stationery_inkwell_delhi",
]


def _by_vendor(claim: dict) -> dict[str, dict]:
    return {
        line["extracted"]["doc_type"]["value"] + ":" + line["extracted"]["vendor_name"]["value"]: line
        for line in claim["lines"]
    }


def test_gallery_claim_end_to_end(client: TestClient, container: Container) -> None:
    claim = client.post("/api/claims", json={"title": "Bengaluru client visit"}).json()
    assert claim["status"] == "draft"
    r = client.post(f"/api/claims/{claim['id']}/documents/from-demo", json={"names": GALLERY})
    assert r.status_code == 202
    assert len(r.json()["document_ids"]) == 5

    claim = wait_processed(client, claim["id"])
    lines = _by_vendor(claim)
    assert len(lines) == 5
    dinner = lines["invoice:Chaiwala Corner Pvt Ltd"]
    hotel = lines["hotel_folio:Harbourview Residency"]
    upi = lines["upi_screenshot:Harbourview Residency"]
    ride = lines["ride_receipt:RydeGo Mobility Pvt Ltd"]
    office = lines["invoice:INKWELL STATIONERS"]

    # UPI screenshot is proof for the hotel, not a second expense.
    assert upi["status"] == "excluded"
    assert hotel["linked_proof_line_id"] == upi["id"]
    # GSTIN fails checksum on a 6,490 invoice -> blocked by policy 3.1.
    assert office["status"] == "excluded"
    assert {f["rule_id"] for f in office["findings"]} >= {"GST_INVOICE_ABOVE_5000", "VAL_GSTIN_INVALID"}
    # Caps applied deterministically.
    assert dinner["reimbursable_inr"] == 3000.0
    assert hotel["reimbursable_inr"] == 6000.0
    assert ride["status"] == "complete"
    assert claim["total_inr"] == 3780 + 8064 + 486 + 6490

    questions = claim["open_questions"]
    assert {q["kind"] for q in questions} == {"justify_flag"}
    assert {q["line_id"] for q in questions} == {dinner["id"], hotel["id"]}
    assert client.post(f"/api/claims/{claim['id']}/submit").status_code == 409

    answers = [
        {"question_id": q["id"], "value": "Client dinner; approved by department head."} for q in questions
    ]
    claim = client.post(f"/api/claims/{claim['id']}/answers", json=answers).json()
    assert claim["status"] == "ready_to_submit"
    assert claim["open_questions"] == []
    assert claim["reimbursable_inr"] == 3000 + 6000 + 486
    assert claim["questions_asked"] == 2
    assert len(claim["documents"]) == 5

    ref = client.post(f"/api/claims/{claim['id']}/submit").json()["finance_reference"]
    assert ref.startswith("FIN-")
    claim = client.get(f"/api/claims/{claim['id']}").json()
    assert claim["status"] == "submitted"
    sub = client.get(f"/api/finance/submissions/{ref}").json()
    assert sub["payload"]["total_reimbursable_inr"] == 9486
    assert client.post(f"/api/claims/{claim['id']}/answers", json=[]).status_code == 409

    audit = client.get(f"/api/claims/{claim['id']}/audit").json()
    assert any(
        row["rule_id"] == "MEALS_CAP_PER_PERSON" and row["policy_section"] == "4.2 Meals"
        for row in audit["findings"]
    )
    assert {s["name"] for s in audit["spans"]} >= {
        "ingest",
        "extract",
        "llm",
        "validate",
        "dedupe",
        "rules",
        "submit",
    }

    # Same file again in a new claim: caught as a duplicate of the submitted one.
    second = client.post("/api/claims", json={}).json()
    client.post(
        f"/api/claims/{second['id']}/documents/from-demo", json={"names": ["restaurant_chaiwala_mumbai"]}
    )
    second = wait_processed(client, second["id"])
    dup = second["lines"][0]
    assert dup["status"] == "excluded"
    finding = next(f for f in dup["findings"] if f["kind"] == "duplicate")
    assert finding["evidence"]["layer"] == "perceptual"
    assert finding["evidence"]["matched_claim_id"] == claim["id"]
    assert finding["severity"] == "block"

    # Override the duplicate -> the line comes back.
    second = client.post(
        f"/api/claims/{second['id']}/lines/{dup['id']}/actions", json={"action": "override_duplicate"}
    ).json()
    assert second["lines"][0]["status"] in ("flagged", "complete")

    overview = client.get("/api/admin/metrics/overview?days=30").json()
    assert overview["kpis"]["claims_total"] == 2
    assert overview["kpis"]["duplicate_inr_prevented"] == 0  # overridden by the user
    assert {d["layer"] for d in overview["duplicates_by_layer"]} == {"perceptual", "fuzzy", "semantic"}


def test_unknown_upload_is_not_in_demo_set(client: TestClient) -> None:
    claim = client.post("/api/claims", json={}).json()
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
    r = client.post(
        f"/api/claims/{claim['id']}/documents", files=[("files", ("new.png", buf.getvalue(), "image/png"))]
    )
    assert r.status_code == 409
    assert "demo set" in r.json()["detail"]
    assert client.get(f"/api/claims/{claim['id']}").json()["processing"] == 0
