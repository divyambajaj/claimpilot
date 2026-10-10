"""PII redaction of persisted extraction output."""

import pytest

from app.pipeline.redact import redact, redact_text
from tests.factories import FakeProvider, extraction_payload


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("Ph 8571972154", "Ph XXXXXXXX54"),
        ("Tel: +91 98765 43210", "Tel: +91 XXXXX XXX10"),
        ("Recharge of Mobile 9876543210", "Recharge of Mobile XXXXXXXX10"),
        ("rohan.desai-1@okhdfcbank", "r****.*****-1@okhdfcbank"),
        ("9876543210@paynow", "9********0@paynow"),
        ("paytmqr2810050501011abcd@paytm", "paytmqr2810050501011abcd@paytm"),  # merchant QR id kept
        ("mail kavya.mehta@example.com", "mail k****.****a@example.com"),
        ("CARD (VISA xx4821)", "CARD (VISA xx••••)"),
        ("Card 4111 1111 1111 1111", "Card •••• •••• •••• ••••"),
        ("Card 4111 1111 1111 1112", "Card 4111 1111 1111 1112"),  # not a card number (Luhn)
        ("A/c No: 123456789012", "A/c No: XXXXXXXX9012"),
        ("Account number XXXX4821", "Account number XXXX••••"),
    ],
)
def test_redact_text(text: str, masked: str) -> None:
    assert redact_text(text) == masked
    assert redact_text(masked) == masked  # idempotent: replayed recordings are already masked


def test_keeps_what_decisions_need() -> None:
    text = "UPI Ref 428913765012\nGSTIN 27AAKCC4821M1ZV\nTotal Rs. 2,800.00\nPaid to Rohan Desai\nFSSAI 11234567890123"
    assert redact_text(text) == text
    assert redact({"a": ["Ph 8571972154", 3, None], "b": {"c": "x"}}) == {
        "a": ["Ph XXXXXXXX54", 3, None],
        "b": {"c": "x"},
    }


async def test_client_redacts_before_parse_and_record(make_client, tmp_path) -> None:
    from app.llm.base import ImageInput
    from app.llm.recorder import Recorder

    payload = extraction_payload(payer_name="K. Mehta", raw_text="From K. Mehta 9876543210@paynow")
    payload["payer_name"]["source_snippet"] = "K. Mehta (9876543210)"
    client = make_client(FakeProvider([payload]), Recorder(tmp_path))
    receipt, resp = await client.extract([ImageInput(data=b"x", key="k:0", path="/x.png")])
    assert receipt.raw_text == "From K. Mehta 9********0@paynow"
    assert receipt.payer_name.source_snippet == "K. Mehta (XXXXXXXX10)"
    saved = next(tmp_path.glob("*.json")).read_text()
    assert "9876543210" not in saved and resp.data["raw_text"] == receipt.raw_text
