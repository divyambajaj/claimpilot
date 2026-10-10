"""Render the curated demo gallery: one Mumbai client trip (5-6 Oct 2026), thirteen documents.

Story beats: airport ride and a re-photographed copy of it (duplicate), a dinner over the per-person meal
cap, a hotel folio paid by UPI plus its payment screenshot (linked as proof), a handwritten fuel bill with a
smudged date (the agent asks for the date and a trip note), a stationery invoice over Rs 5,000 whose GSTIN fails
the checksum (blocked), and a UPI transfer to a colleague for a shared cab (a person-to-person payment: blocked).

Run explicitly: `uv run python backend/scripts/make_demo_receipts.py`, then `make record-demo`. Replay
fingerprints hash the file bytes, so regenerating means re-recording.
"""

import datetime as dt
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT
from app.evaluation.synth import augment
from app.evaluation.synth.generator import (
    build_handwritten,
    build_hotel,
    build_restaurant,
    build_ride,
    build_stationery,
    build_upi,
)
from app.evaluation.synth.render import TEMPLATES

OUT = REPO_ROOT / "data" / "demo_receipts"
D1, D2 = dt.date(2026, 10, 5), dt.date(2026, 10, 6)


def rng(name: str) -> random.Random:
    return random.Random(f"demo:{name}")


def ride(name: str, date, total: float, method: str, pickup: str, drop: str, when: tuple[str, str]):
    doc, fields, items = build_ride(rng(name), "Mumbai", date, total, method)
    doc.update(
        pickup=f"{pickup}, Mumbai",
        drop=f"{drop}, Mumbai",
        pickup_time=when[0],
        drop_time=when[1],
        rider="Mehta",
        daypart="morning" if when[0] < "12" else "evening",
    )
    return doc, fields, items


def main() -> None:
    hotel = build_hotel(rng("hotel"), "harbour_mum", D2, 1, 5200, "upi")
    hotel[0]["guest"] = "K. Mehta"
    airport = ride("airport", D1, 642, "upi", "CSMT Airport T2", "Bandra Kurla Complex", ("09:12", "09:58"))
    docs = {
        "ride_rydego_airport.png": (
            "ride",
            airport,
            [],
            ("Airport ride, RydeGo", "ride_receipt", "Airport to client office, paid by UPI"),
        ),
        "ride_rydego_airport_photo.jpg": (
            "ride",
            airport,
            ["crop", "perspective", "rotate", "crumple", "jpeg"],
            (
                "Airport ride (photo of the same receipt)",
                "ride_receipt",
                "Re-photographed copy of the airport ride",
            ),
        ),
        "lunch_konkan_thali.png": (
            "restaurant",
            build_restaurant(rng("konkan"), "konkan", D1, 2, 590),
            [],
            ("Working lunch, Konkan Thali House", "invoice", "GST bill, 2 covers"),
        ),
        "dinner_chaiwala_corner.png": (
            "restaurant",
            build_restaurant(rng("chaiwala"), "chaiwala", D1, 4, 945),
            [],
            ("Client dinner, Chaiwala Corner", "invoice", "GST bill, 4 covers, above the per-person cap"),
        ),
        "hotel_harbourview_mumbai.png": (
            "hotel",
            hotel,
            [],
            (
                "Hotel folio, Harbourview Residency",
                "hotel_folio",
                "One night at Marine Drive, settled by UPI",
            ),
        ),
        "upi_paynow_harbourview.png": (
            "upi",
            build_upi(rng("upi"), "Harbourview Residency", D2, hotel[1]["total_amount"]),
            [],
            (
                "UPI payment, Harbourview Residency",
                "upi_screenshot",
                "Payment screenshot for the hotel folio",
            ),
        ),
        "ride_rydego_hotel_client.png": (
            "ride",
            ride(
                "hotel_client",
                D2,
                318,
                "card",
                "Marine Drive, Churchgate",
                "Nariman Point",
                ("09:40", "09:58"),
            ),
            [],
            ("Hotel to client, RydeGo", "ride_receipt", "Short ride, card"),
        ),
        "coffee_bandra_bean.png": (
            "restaurant",
            build_restaurant(rng("bean"), "bandrabean", D2, 3, 290),
            ["rotate"],
            ("Coffee meeting, Bandra Bean Co.", "receipt", "3 covers, photographed at an angle"),
        ),
        "lunch_malabar_coast.png": (
            "restaurant",
            build_restaurant(rng("malabar"), "malabar", D2, 3, 715),
            [],
            ("Client lunch, Malabar Coast Kitchen", "invoice", "GST bill, 3 covers, just under the cap"),
        ),
        "fuel_om_sai_handwritten.jpg": (
            "handwritten",
            build_handwritten(rng("fuel"), "omsai", D2, smudge=True, lines=[("Petrol (Ltr)", 15, 103)]),
            ["crumple"],
            ("Fuel, Om Sai Fuel Centre", "handwritten", "Handwritten cash bill, date smudged"),
        ),
        "stationery_fort_mart.png": (
            "stationery",
            build_stationery(rng("fort"), "fort", D2, 3, 6490, "card", "invalid"),
            [],
            (
                "Presentation supplies, Fort Stationery Mart",
                "invoice",
                "Tax invoice above Rs 5,000; GSTIN fails checksum",
            ),
        ),
        "upi_paynow_cab_share.png": (
            "upi",
            build_upi(
                rng("p2p"),
                "Rohan Desai",
                D2,
                350.0,
                vpa="rohan.desai-2@okpaynow",
                note="Cab share",
                kind="individual",
            ),
            [],
            (
                "UPI transfer to Rohan Desai",
                "upi_screenshot",
                "Cab fare paid back to a colleague's personal UPI ID",
            ),
        ),
        "ride_rydego_return_airport.png": (
            "ride",
            ride("return", D2, 705, "upi", "Bandra Kurla Complex", "CSMT Airport T2", ("18:05", "18:49")),
            [],
            ("Return ride, RydeGo", "ride_receipt", "Client office to airport, paid by UPI"),
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        if old.suffix in (".png", ".jpg"):
            old.unlink()
    manifest = {}
    for name, (template, (doc, fields, _), augs, (title, doc_type, description)) in docs.items():
        r = rng(f"render:{name}")
        img, _ = TEMPLATES[template](doc, r)
        img = augment.apply(img, augs, r)
        buf = io.BytesIO()
        img.save(
            buf,
            format="JPEG" if name.endswith(".jpg") else "PNG",
            **({"quality": 88} if name.endswith(".jpg") else {"optimize": True}),
        )
        (OUT / name).write_bytes(buf.getvalue())
        manifest[name] = {
            "title": title,
            "doc_type": doc_type,
            "description": description,
            "amount_inr": fields["total_amount"],
        }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(docs)} receipts to {OUT}")


if __name__ == "__main__":
    main()
