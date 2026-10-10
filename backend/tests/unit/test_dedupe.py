"""Duplicate detection layers, UPI linking and the detector."""

import datetime as dt

import numpy as np

from app.domain.enums import FindingKind, Severity
from app.domain.models import Document
from app.pipeline.dedupe.detector import DuplicateDetector, apply_upi_link, duplicate_finding
from app.pipeline.dedupe.fuzzy import amount_match, fuzzy_score, norm_vendor
from app.pipeline.dedupe.phash import perceptual_match
from app.pipeline.dedupe.semantic import HashedNgramEmbedder, cosine, line_text
from app.pipeline.dedupe.upi_link import upi_link_evidence
from tests.factories import make_line

DINNER_TEXT = (
    "CHAIWALA CORNER PVT LTD Shop 4, Linking Road, Bandra West, Mumbai 400050 GSTIN 27AAKCC4821M1ZC TAX INVOICE "
    "Bill No: CC/2026/04417 Date: 03/10/2026 Covers: 4 Masala Dosa x4 720.00 Paneer Tikka Platter x2 1,180.00 "
    "Veg Biryani x2 980.00 Filter Coffee x4 360.00 Gulab Jamun x4 360.00 Subtotal 3,600.00 CGST 90.00 SGST 90.00 "
    "GRAND TOTAL 3,780.00"
)
RIDE_A = "RydeGo Ride receipt Invoice RG-PN-551920 06 Oct 2026 Pickup Hinjewadi Phase 1 Drop Koregaon Park Total 486.00"
RIDE_B = "RydeGo Ride receipt Invoice RG-PN-551977 06 Oct 2026 Pickup Baner Drop Pune Airport Total 742.00"


def _doc(doc_id: str, sha: str, dhash: str) -> Document:
    return Document(
        id=doc_id,
        claim_id="C1",
        filename="x.png",
        mime="image/png",
        sha256=sha,
        dhash=dhash,
        dhash_rotations=[dhash, "ffffffffffffffff", "0f0f0f0f0f0f0f0f", "f0f0f0f0f0f0f0f0"],
        width=1,
        height=1,
        stored_path="/x",
    )


class TestPerceptual:
    def test_same_file_and_near_image(self) -> None:
        a = _doc("A", "s1", "8480e08880a09c00")
        assert perceptual_match([a], [_doc("B", "s1", "0000000000000000")]) == (
            1.0,
            {"signal": "sha256", "hamming": 0},
        )
        near = perceptual_match([a], [_doc("B", "s2", "8480e08880a09c03")])
        assert near == (0.97, {"signal": "dhash", "hamming": 2})
        assert perceptual_match([a], [_doc("B", "s3", "7b7f1f777f5f63ff")]) is None


class TestFuzzy:
    def test_same_expense_scores_high(self) -> None:
        a = make_line("A", vendor_name="Chaiwala Corner Pvt Ltd", invoice_number=None)
        b = make_line("B", vendor_name="CHAIWALA CORNER", invoice_number=None, date=dt.date(2026, 10, 4))
        score, ev = fuzzy_score(a, b)
        assert score >= 0.8
        assert ev["vendor_similarity"] == 1.0
        assert ev["date_delta_days"] == 1

    def test_two_rides_same_day_different_amounts(self) -> None:
        a = make_line("A", vendor_name="RydeGo", total_amount=486.0, invoice_number="RG-1")
        b = make_line("B", vendor_name="RydeGo", total_amount=742.0, invoice_number="RG-2")
        assert fuzzy_score(a, b)[0] < 0.8

    def test_invoice_number_shortcut(self) -> None:
        a = make_line("A", vendor_name="Inkwell", invoice_number="INK/1093")
        b = make_line("B", vendor_name="Totally Different", invoice_number="ink-1093", date=None)
        assert fuzzy_score(a, b) == (0.98, {"signal": "invoice_number", "invoice_number": "INK1093"})

    def test_helpers(self) -> None:
        assert norm_vendor("Harbourview Residency Pvt. Ltd.") == "harbourview residency"
        assert norm_vendor(None) == ""
        assert amount_match(1000.0, 1004.0)
        assert not amount_match(1000.0, 1010.0)
        assert not amount_match(None, 5.0)
        score, ev = fuzzy_score(
            make_line("A", vendor_name=None, date=None, invoice_number=None), make_line("B")
        )
        assert ev["date_delta_days"] is None
        assert score == 0.35


class TestSemantic:
    emb = HashedNgramEmbedder()

    def test_deterministic_and_unit(self) -> None:
        v = self.emb.embed(DINNER_TEXT)
        assert np.array_equal(v, HashedNgramEmbedder().embed(DINNER_TEXT))
        assert abs(cosine(v, v) - 1.0) < 1e-5
        assert not self.emb.embed("").any()

    def test_perturbed_high_unrelated_low(self) -> None:
        reread = (
            DINNER_TEXT.replace("Bandra West", "Bandra W.")
            .replace("GRAND TOTAL", "Grand Total")
            .replace(",", "")
        )
        assert cosine(self.emb.embed(DINNER_TEXT), self.emb.embed(reread)) >= 0.85
        assert cosine(self.emb.embed(DINNER_TEXT), self.emb.embed(RIDE_A)) < 0.5

    def test_line_text_includes_items(self) -> None:
        line = make_line(raw_text="bill", items=[{"description": "Dosa"}])
        assert line_text(line) == "bill Dosa"


class TestUpiLink:
    upi = {
        "doc_type": "upi_screenshot",
        "vendor_name": "Harbourview Residency",
        "payee_name": "Harbourview Residency",
        "total_amount": 8064.0,
        "date": dt.date(2026, 10, 5),
        "upi_txn_id": "627814430915",
        "category": "lodging",
    }
    bill = {
        "doc_type": "hotel_folio",
        "vendor_name": "Harbourview Residency Pvt Ltd",
        "total_amount": 8064.0,
        "date": dt.date(2026, 10, 5),
        "category": "lodging",
    }

    def test_links(self) -> None:
        ev = upi_link_evidence(make_line("U", **self.upi), make_line("H", **self.bill))
        assert ev == {"layer": "upi_link", "payee_similarity": 1.0, "txn_id_in_invoice": False}

    def test_amount_or_date_mismatch(self) -> None:
        assert (
            upi_link_evidence(
                make_line("U", **{**self.upi, "total_amount": 8100.0}), make_line("H", **self.bill)
            )
            is None
        )
        far = {**self.upi, "date": dt.date(2026, 10, 9)}
        assert upi_link_evidence(make_line("U", **far), make_line("H", **self.bill)) is None
        assert (
            upi_link_evidence(make_line("U", **{**self.upi, "date": None}), make_line("H", **self.bill))
            is None
        )

    def test_txn_id_rescues_poor_payee(self) -> None:
        upi = {**self.upi, "payee_name": "HRV HOSPITALITY", "vendor_name": "HRV HOSPITALITY"}
        bill = make_line("H", raw_text="Folio paid via UPI ref 6278 1443 0915", **self.bill)
        assert upi_link_evidence(make_line("U", **upi), bill)["txn_id_in_invoice"] is True
        assert upi_link_evidence(make_line("U", **upi), make_line("H", **self.bill)) is None

    def test_wrong_kinds(self) -> None:
        assert upi_link_evidence(make_line("H", **self.bill), make_line("H2", **self.bill)) is None
        assert upi_link_evidence(make_line("U", **self.upi), make_line("U2", **self.upi)) is None


class TestDetector:
    det = DuplicateDetector()

    def test_layer_order_and_evidence(self) -> None:
        docs = {
            "D-A": _doc("D-A", "same", "8480e08880a09c00"),
            "D-B": _doc("D-B", "same", "8480e08880a09c00"),
        }
        a, b = make_line("A", raw_text=DINNER_TEXT), make_line("B", raw_text=DINNER_TEXT)
        match = self.det.find_duplicate(b, [a], docs)
        assert (match.layer, match.score, match.same_file) == ("perceptual", 1.0, True)
        assert set(match.evidence) == {"perceptual", "fuzzy", "semantic"}
        finding = duplicate_finding(b, match)
        assert finding.severity == Severity.BLOCK
        assert finding.kind == FindingKind.DUPLICATE
        assert finding.evidence["matched_line_id"] == "A"
        assert "same file" in finding.message

    def test_fuzzy_then_semantic(self) -> None:
        a = make_line("A", raw_text=DINNER_TEXT)
        b = make_line("B", raw_text="different crop", date=dt.date(2026, 10, 4))
        assert self.det.find_duplicate(b, [a], {}).layer == "fuzzy"
        reprint = make_line(
            "C",
            raw_text=DINNER_TEXT.replace("Bandra West", "Bandra W."),
            vendor_name="CC Foods",
            date=dt.date(2026, 9, 1),
            invoice_number=None,
            claim_id="C0",
        )
        match = self.det.find_duplicate(reprint, [a], {})
        assert (match.layer, match.score) == ("semantic", 0.9)
        finding = duplicate_finding(make_line("N", claim_id="C9"), match)
        assert finding.severity == Severity.WARN
        assert "earlier claim" in finding.message

    def test_decoys_and_kind_filter(self) -> None:
        ride_a = make_line(
            "A",
            vendor_name="RydeGo",
            total_amount=486.0,
            invoice_number="RG-1",
            raw_text=RIDE_A,
            category="travel_local",
        )
        ride_b = make_line(
            "B",
            vendor_name="RydeGo",
            total_amount=742.0,
            invoice_number="RG-2",
            raw_text=RIDE_B,
            category="travel_local",
        )
        assert self.det.find_duplicate(ride_b, [ride_a, ride_b], {}) is None
        upi = make_line(
            "U", doc_type="upi_screenshot", raw_text=RIDE_A, vendor_name="RydeGo", total_amount=486.0
        )
        assert self.det.find_duplicate(upi, [ride_a], {}) is None

    def test_upi_link_both_orders_and_apply(self) -> None:
        upi = make_line("U", **TestUpiLink.upi)
        bill = make_line("H", **TestUpiLink.bill)
        link = self.det.find_upi_link(upi, [bill, upi])
        assert (link.upi_line_id, link.invoice_line_id) == ("U", "H")
        reverse = self.det.find_upi_link(bill, [upi, bill])
        assert (reverse.upi_line_id, reverse.invoice_line_id) == ("U", "H")
        upi2, bill2 = apply_upi_link(upi, bill, link)
        assert upi2.linked_to_line_id == "H"
        assert upi2.findings[-1].evidence["linked_to"] == "H"
        assert bill2.has_proof_of_payment
        assert bill2.linked_proof_line_id == "U"
        assert bill2.document_ids == ["D-H", "D-U"]
        assert self.det.find_upi_link(make_line("U3", **TestUpiLink.upi), [bill2]) is None
        assert (
            self.det.find_upi_link(bill, [bill.model_copy(update={"id": "X", "user_excluded": True})]) is None
        )
