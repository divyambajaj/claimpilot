"""Ingest, extraction post-processing and validators."""

import asyncio
import datetime as dt
import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.config import REPO_ROOT
from app.llm.base import ImageInput
from app.llm.client import LLMClient
from app.llm.prompts.registry import PromptRegistry
from app.llm.providers.replay import ReplayProvider
from app.observability.tracing import Tracer
from app.pipeline.extract import (
    amount_in_inr,
    extraction_schema,
    normalize_extraction,
    parse_amount,
    parse_date,
    parse_extraction,
)
from app.pipeline.ingest import IngestError, dhash, hamming, ingest_bytes, sniff_mime
from app.pipeline.validate.arithmetic import check_arithmetic
from app.pipeline.validate.confidence import adjust_confidence, validation_findings
from app.pipeline.validate.dates import date_problem
from app.pipeline.validate.gstin import checksum_char, gstin_problem, is_valid_gstin, make_gstin
from tests.factories import TODAY, VALID_GSTIN, make_receipt

DEMO = REPO_ROOT / "backend" / "tests" / "fixtures" / "demo_v1"


def _receipt_image(seed: int, size: tuple[int, int] = (600, 800)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for i in range(12):
        y = 40 + i * 55
        d.rectangle((40, y, 40 + ((seed * 37 + i * 91) % 480), y + 25), fill=(30, 30, 30))
    return img


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestIngest:
    def test_same_bytes_decoded_once_and_warmed_from_folder(self, tmp_path: Path) -> None:
        from app.pipeline.ingest import _ingest, warm_ingest

        data = _png(_receipt_image(99))
        (tmp_path / "r.png").write_bytes(data)
        (tmp_path / "manifest.json").write_text("{}")
        _ingest.cache_clear()
        warm_ingest(tmp_path)  # the non-image file is skipped
        assert _ingest.cache_info().currsize == 1
        assert ingest_bytes(data) == ingest_bytes(data)
        assert _ingest.cache_info().hits == 2

    def test_png_normalized_and_downsized(self) -> None:
        mime, pages = ingest_bytes(_png(_receipt_image(1, (2400, 3200))))
        assert mime == "image/png"
        assert len(pages) == 1
        p = pages[0]
        assert max(p.width, p.height) == 1600
        assert len(p.dhash) == 16 and len(p.dhash_rotations) == 4
        assert p.replay_key.endswith(":0")

    def test_exif_orientation_applied(self) -> None:
        img = _receipt_image(2, (400, 300))
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 270 on display
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)
        _, pages = ingest_bytes(buf.getvalue())
        assert (pages[0].width, pages[0].height) == (300, 400)

    def test_pdf_pages(self) -> None:
        buf = io.BytesIO()
        _receipt_image(3).save(buf, format="PDF", save_all=True, append_images=[_receipt_image(4)])
        mime, pages = ingest_bytes(buf.getvalue())
        assert mime == "application/pdf"
        assert [p.page for p in pages] == [0, 1]
        assert pages[0].source_sha256 == pages[1].source_sha256

    @pytest.mark.parametrize("data", [b"GIF89a....", b"%PDF-1.4 garbage", b"\x89PNG\r\n\x1a\nbroken"])
    def test_rejects_bad_input(self, data: bytes) -> None:
        with pytest.raises(IngestError):
            ingest_bytes(data)

    def test_sniff_webp(self) -> None:
        assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"


class TestDhash:
    def test_identical_zero_and_different_far(self) -> None:
        a = _receipt_image(1)
        assert hamming(dhash(a), dhash(a)) == 0
        # Receipts share a white-dominated layout, so distinct documents sit ~12-28 bits apart.
        hashes = [ingest_bytes(p.read_bytes())[1][0].dhash for p in sorted(DEMO.glob("*.png"))]
        assert min(hamming(x, y) for i, x in enumerate(hashes) for y in hashes[i + 1 :]) > 10

    def test_rotation_and_blur_robust(self) -> None:
        a = _receipt_image(5)
        _, pages = ingest_bytes(_png(a))
        rotated = ingest_bytes(_png(a.rotate(90, expand=True)))[1][0]
        assert min(hamming(r, pages[0].dhash) for r in rotated.dhash_rotations) <= 6
        blurred = dhash(a.filter(ImageFilter.GaussianBlur(1.2)))
        assert hamming(blurred, pages[0].dhash) <= 6


class TestGstin:
    GOOD = [
        make_gstin(state, pan)
        for state, pan in [
            ("27", "AAKCC4821M"),
            ("29", "AADFH7310K"),
            ("07", "AAGFI3092B"),
            ("33", "AABCT1234D"),
            ("09", "AAACZ9999Z"),
            ("24", "BBBPS0001A"),
            ("19", "AAFCV5678E"),
            ("36", "AAHCR4321F"),
            ("06", "AAICM1111G"),
            ("32", "AAJCK2222H"),
        ]
    ]

    def test_valid(self) -> None:
        assert all(is_valid_gstin(g) for g in self.GOOD)
        assert is_valid_gstin(self.GOOD[0].lower()[:5] + " " + self.GOOD[0].lower()[5:])

    def test_known_checksum(self) -> None:
        assert checksum_char("27AAPFU0939F1Z") == "V"  # widely published sample GSTIN 27AAPFU0939F1ZV

    @pytest.mark.parametrize("pos", range(14))
    def test_single_char_corruption_fails(self, pos: int) -> None:
        g = self.GOOD[0]
        replacement = "0" if g[pos] != "0" else "1"
        corrupted = g[:pos] + replacement + g[pos + 1 :]
        assert not is_valid_gstin(corrupted)

    def test_reasons(self) -> None:
        assert gstin_problem(None) == "missing"
        assert "15-character" in gstin_problem("27ABC")
        assert "state code" in gstin_problem(make_gstin("45", "AAKCC4821M"))
        assert "check digit" in gstin_problem(self.GOOD[0][:14] + ("X" if self.GOOD[0][14] != "X" else "Y"))


class TestArithmetic:
    def test_reconciles_and_detects_slab(self) -> None:
        r = make_receipt(subtotal=1000.0, tax_amount=180.0, total_amount=1180.0)
        check = check_arithmetic(r)
        assert check.totals_reconcile is True
        assert check.gst_rate == 0.18

    def test_mismatch_and_items(self) -> None:
        r = make_receipt(
            subtotal=1000.0,
            tax_amount=50.0,
            total_amount=1200.0,
            items=[{"description": "a", "amount": 600.0}, {"description": "b", "amount": 400.0}],
        )
        check = check_arithmetic(r)
        assert check.totals_reconcile is False
        assert check.items_reconcile is True  # items match subtotal
        assert check.gst_rate == 0.05

    def test_insufficient_fields(self) -> None:
        check = check_arithmetic(make_receipt(subtotal=None, tax_amount=None))
        assert (check.totals_reconcile, check.items_reconcile, check.gst_rate) == (None, None, None)

    def test_rounding_tolerance(self) -> None:
        assert check_arithmetic(
            make_receipt(subtotal=442.86, tax_amount=22.14, total_amount=465.4)
        ).totals_reconcile


class TestDates:
    def test_problems(self) -> None:
        assert date_problem(None, TODAY) is None
        assert date_problem(TODAY, TODAY) is None
        assert "future" in date_problem(TODAY + dt.timedelta(days=5), TODAY)
        assert "365" in date_problem(TODAY - dt.timedelta(days=400), TODAY)


class TestConfidence:
    def test_checksum_failure_zeroes_gstin(self) -> None:
        bad = VALID_GSTIN[:14] + ("A" if VALID_GSTIN[14] != "A" else "B")
        r = adjust_confidence(make_receipt(vendor_gstin=bad), TODAY)
        assert r.vendor_gstin.confidence == 0.0
        assert r.vendor_gstin.origin == "validator"
        findings = validation_findings(r, "L1", TODAY)
        assert [f.rule_id for f in findings] == ["VAL_GSTIN_INVALID"]
        assert findings[0].id == "L1:VAL_GSTIN_INVALID"

    def test_reconciled_total_boosted_and_capped(self) -> None:
        r = make_receipt(subtotal=1000.0, tax_amount=180.0, total_amount=1180.0, conf={"total_amount": 0.9})
        assert adjust_confidence(r, TODAY).total_amount.confidence == 0.99
        r2 = make_receipt(subtotal=1000.0, tax_amount=180.0, total_amount=1180.0, conf={"total_amount": 0.7})
        assert adjust_confidence(r2, TODAY).total_amount.confidence == pytest.approx(0.85)

    def test_mismatch_penalised_with_finding(self) -> None:
        r = make_receipt(subtotal=1000.0, tax_amount=10.0, total_amount=1500.0, conf={"total_amount": 0.9})
        adjusted = adjust_confidence(r, TODAY)
        assert adjusted.total_amount.confidence == pytest.approx(0.7)
        assert "VAL_TOTAL_MISMATCH" in {f.rule_id for f in validation_findings(adjusted, "L1", TODAY)}

    def test_blurry_lowers_all_and_future_date_capped(self) -> None:
        r = make_receipt(quality="blurry", date=TODAY + dt.timedelta(days=30), conf={"vendor_name": 0.9})
        adjusted = adjust_confidence(r, TODAY)
        assert adjusted.vendor_name.confidence == pytest.approx(0.8)
        assert adjusted.date.confidence == 0.3
        assert r.vendor_name.confidence == 0.9  # input untouched
        assert "VAL_DATE_IMPLAUSIBLE" in {f.rule_id for f in validation_findings(adjusted, "L1", TODAY)}

    def test_items_mismatch_finding(self) -> None:
        r = make_receipt(items=[{"description": "x", "amount": 10.0}], total_amount=500.0)
        assert [f.rule_id for f in validation_findings(r, "L", TODAY)] == ["VAL_ITEMS_MISMATCH"]


class TestExtractPostProcessing:
    def test_parsers(self) -> None:
        assert parse_date("03/10/2026") == dt.date(2026, 10, 3)
        assert parse_date("05 Oct 2026") == dt.date(2026, 10, 5)
        assert parse_date("2026-10-06") == dt.date(2026, 10, 6)
        assert parse_date("yesterday") is None
        assert parse_amount("₹ 3,780.00") == 3780.0
        assert parse_amount("Rs. 486/-") == 486.0
        assert parse_amount("n/a") is None
        assert parse_amount(True) is None

    def test_normalize_coerces_messy_output(self) -> None:
        raw = {
            "doc_type": {"value": "Tax Invoice", "confidence": 90},
            "vendor_gstin": {"value": "27aakcc 4821m1zc", "confidence": 0.9, "source_snippet": "GSTIN"},
            "date": {"value": "31/31/2026", "confidence": 0.9},
            "total_amount": {"value": "1,234.50", "confidence": 0.8},
            "attendees_count": {"value": "4", "confidence": 0.7},
            "currency": {"value": None, "confidence": 0.0},
            "category": "meals",
            "items": [{"description": "Dosa", "amount": "120"}, {"amount": 5}],
            "raw_text": "text",
            "quality": "weird",
        }
        out = normalize_extraction(raw)
        assert out["doc_type"] == {"value": "unknown", "confidence": 0.3, "source_snippet": None}
        assert out["vendor_gstin"]["value"] == "27AAKCC4821M1ZC"
        assert out["date"]["value"] is None and out["date"]["confidence"] == 0.0
        assert out["total_amount"]["value"] == 1234.5
        assert out["attendees_count"]["value"] == 4
        assert out["currency"] == {
            "value": "INR",
            "confidence": 0.6,
            "source_snippet": None,
            "origin": "assumed",
        }
        assert out["category"]["value"] == "meals"
        assert out["vendor_name"] == {"value": None, "confidence": 0.0, "source_snippet": None}
        assert out["items"] == [
            {"description": "Dosa", "quantity": None, "unit_price": None, "amount": 120.0}
        ]
        assert out["quality"] == "good"

    def test_parse_requires_raw_text(self) -> None:
        with pytest.raises(ValueError, match="raw_text"):
            parse_extraction({"vendor_name": {"value": "x", "confidence": 1}})

    def test_schema_shapes(self) -> None:
        full, core = extraction_schema(), extraction_schema(core=True)
        assert full["additionalProperties"] is False
        assert set(full["required"]) == set(full["properties"])
        assert len(core["properties"]) < len(full["properties"])

    def test_amount_in_inr(self) -> None:
        assert amount_in_inr(make_receipt(total_amount=10.0, currency="USD")) == 840.0
        assert amount_in_inr(make_receipt(total_amount=None)) == 0.0


class TestRecordedDemoReceipts:
    """The committed demo receipts replay through the real ingest + client path with no network."""

    EXPECTED = {
        "restaurant_chaiwala_mumbai.png": ("2026-10-03", 3780.0, "meals"),
        "hotel_harbourview_bengaluru.png": ("2026-10-05", 8064.0, "lodging"),
        "upi_paynow_harbourview.png": ("2026-10-05", 8064.0, "lodging"),
        "ride_rydego_pune.png": ("2026-10-06", 486.0, "travel_local"),
        "stationery_inkwell_delhi.png": ("2026-10-02", 6490.0, "office"),
    }

    @pytest.mark.parametrize("name", sorted(EXPECTED))
    def test_replay(self, name: str) -> None:
        client = LLMClient(
            ReplayProvider(REPO_ROOT / "data" / "replay"),
            None,
            asyncio.Semaphore(1),
            Tracer(None),
            PromptRegistry(),
        )
        _, pages = ingest_bytes((DEMO / name).read_bytes())
        images = [
            ImageInput(data=p.png, key=p.replay_key, path=str(Path("/elsewhere") / name)) for p in pages
        ]
        receipt, resp = asyncio.run(client.extract(images, "v2"))  # legacy gallery: recorded with v1/v2
        assert resp.replayed
        date, total, category = self.EXPECTED[name]
        assert (str(receipt.date.value), receipt.total_amount.value, receipt.category.value) == (
            date,
            total,
            category,
        )
