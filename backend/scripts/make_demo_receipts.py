"""Render the curated demo receipts (fictional vendors, checksum-valid GSTINs) into data/demo_receipts/.

The gallery metadata lives in data/demo_receipts/manifest.json (edited by hand).
Run explicitly: `uv run python backend/scripts/make_demo_receipts.py`. Committed outputs are what replay
fingerprints point at, so do not regenerate them casually.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT
from app.pipeline.validate.gstin import make_gstin

OUT = REPO_ROOT / "data" / "demo_receipts"
WIDTH = 820


def render(lines: list[tuple[str, int, str]], path: Path) -> None:
    """lines: (text, font size, align: l|c|r|lr where 'lr' splits on '|')."""
    height = 80 + sum(size + 14 for _, size, _ in lines)
    img = Image.new("RGB", (WIDTH, height), (252, 251, 247))
    draw = ImageDraw.Draw(img)
    y = 40
    for text, size, align in lines:
        font = ImageFont.load_default(size=size)
        if align == "lr":
            left, right = text.split("|")
            draw.text((50, y), left, fill=(25, 25, 25), font=font)
            w = draw.textlength(right, font=font)
            draw.text((WIDTH - 50 - w, y), right, fill=(25, 25, 25), font=font)
        elif align == "c":
            w = draw.textlength(text, font=font)
            draw.text(((WIDTH - w) / 2, y), text, fill=(25, 25, 25), font=font)
        elif text == "---":
            draw.line((50, y + size // 2, WIDTH - 50, y + size // 2), fill=(120, 120, 120), width=2)
        else:
            draw.text((50, y), text, fill=(25, 25, 25), font=font)
        y += size + 14
    img.save(path, format="PNG")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    chaiwala = make_gstin("27", "AAKCC4821M")
    harbour = make_gstin("29", "AADFH7310K")
    rydego = make_gstin("27", "AAJCR5521Q")
    bad_gstin = make_gstin("07", "AAGFI3092B")[:14] + "X"  # deliberately wrong check digit
    receipts = {
        "restaurant_chaiwala_mumbai.png": [
            ("CHAIWALA CORNER PVT LTD", 34, "c"),
            ("Shop 4, Linking Road, Bandra West, Mumbai 400050", 18, "c"),
            (f"GSTIN: {chaiwala}", 20, "c"),
            ("TAX INVOICE", 24, "c"),
            ("---", 18, "l"),
            ("Bill No: CC/2026/04417|Date: 03/10/2026", 20, "lr"),
            ("Table: 12   Covers: 4|Time: 21:14", 20, "lr"),
            ("---", 18, "l"),
            ("Masala Dosa x4|720.00", 22, "lr"),
            ("Paneer Tikka Platter x2|1,180.00", 22, "lr"),
            ("Veg Biryani x2|980.00", 22, "lr"),
            ("Filter Coffee x4|360.00", 22, "lr"),
            ("Gulab Jamun x4|360.00", 22, "lr"),
            ("---", 18, "l"),
            ("Subtotal|3,600.00", 22, "lr"),
            ("CGST @ 2.5%|90.00", 22, "lr"),
            ("SGST @ 2.5%|90.00", 22, "lr"),
            ("GRAND TOTAL (INR)|3,780.00", 28, "lr"),
            ("Paid by: CARD (VISA xx4417)", 20, "l"),
            ("Thank you. Visit again!", 18, "c"),
        ],
        "hotel_harbourview_bengaluru.png": [
            ("HARBOURVIEW RESIDENCY", 34, "c"),
            ("14 Residency Road, Bengaluru 560025", 18, "c"),
            (f"GSTIN: {harbour}", 20, "c"),
            ("GUEST FOLIO / TAX INVOICE", 24, "c"),
            ("---", 18, "l"),
            ("Folio No: HR-88213|Date: 05/10/2026", 20, "lr"),
            ("Guest: A. Employee|Room 704", 20, "lr"),
            ("Arrival: 04/10/2026|Departure: 05/10/2026", 20, "lr"),
            ("---", 18, "l"),
            ("Room Tariff (1 night, Deluxe)|7,200.00", 22, "lr"),
            ("---", 18, "l"),
            ("Taxable Value|7,200.00", 22, "lr"),
            ("CGST @ 6%|432.00", 22, "lr"),
            ("SGST @ 6%|432.00", 22, "lr"),
            ("TOTAL (INR)|8,064.00", 28, "lr"),
            ("Settlement: UPI", 20, "l"),
        ],
        "upi_paynow_harbourview.png": [
            ("PayNow", 30, "c"),
            ("Payment Successful", 30, "c"),
            ("Rs. 8,064", 44, "c"),
            ("---", 18, "l"),
            ("Paid to|Harbourview Residency", 22, "lr"),
            ("UPI ID|harbourview@okbank", 22, "lr"),
            ("From|A Employee (xx2291)", 22, "lr"),
            ("Date & time|05 Oct 2026, 11:02 AM", 22, "lr"),
            ("UPI Ref No.|627814430915", 22, "lr"),
            ("Transaction ID|PN2610051102AX77", 22, "lr"),
            ("---", 18, "l"),
            ("Powered by UPI", 18, "c"),
        ],
        "ride_rydego_pune.png": [
            ("RydeGo", 36, "c"),
            ("Ride receipt", 22, "c"),
            (f"RydeGo Mobility Pvt Ltd  GSTIN {rydego}", 18, "c"),
            ("---", 18, "l"),
            ("Invoice: RG-PN-551920|06 Oct 2026", 20, "lr"),
            ("Pickup: Hinjewadi Phase 1, Pune", 20, "l"),
            ("Drop: Koregaon Park, Pune", 20, "l"),
            ("Distance: 21.4 km|Duration: 47 min", 20, "lr"),
            ("---", 18, "l"),
            ("Ride fare|442.86", 22, "lr"),
            ("GST @ 5%|22.14", 22, "lr"),
            ("Platform fee|21.00", 22, "lr"),
            ("Total paid|486.00", 28, "lr"),
            ("Payment: UPI", 20, "l"),
        ],
        "stationery_inkwell_delhi.png": [
            ("INKWELL STATIONERS", 34, "c"),
            ("22 Nehru Place, New Delhi 110019", 18, "c"),
            (f"GSTIN: {bad_gstin}", 20, "c"),
            ("TAX INVOICE", 24, "c"),
            ("---", 18, "l"),
            ("Invoice No: INK/1093|Date: 02/10/2026", 20, "lr"),
            ("---", 18, "l"),
            ("A4 Copier Paper (5 reams)|1,250.00", 22, "lr"),
            ("Whiteboard 4x3 ft|2,600.00", 22, "lr"),
            ("Marker Set & Dusters|1,650.00", 22, "lr"),
            ("---", 18, "l"),
            ("Taxable Value|5,500.00", 22, "lr"),
            ("CGST @ 9%|495.00", 22, "lr"),
            ("SGST @ 9%|495.00", 22, "lr"),
            ("TOTAL (INR)|6,490.00", 28, "lr"),
            ("Payment: CASH", 20, "l"),
        ],
    }
    for name, lines in receipts.items():
        render(lines, OUT / name)
    print(f"wrote {len(receipts)} receipts to {OUT}")


if __name__ == "__main__":
    main()
