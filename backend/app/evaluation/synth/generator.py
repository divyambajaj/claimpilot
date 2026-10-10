"""Seeded synthetic eval set: ~60 Indian expense documents in 12 claims with planted scenarios (section 13).

Writes `data/eval/fixtures/{*.png,*.jpg, ground_truth.jsonl, manifest.json}`. Run explicitly (`make synth`):
regenerating changes image bytes and therefore every replay fingerprint.

Ground truth per fixture: `fields` holds the scored values (a list = any of these is correct, null = must be
empty; a field absent from `fields` is ambiguous on that template and not scored), `expected_rules` the
BLOCK/WARN policy rule ids the engine should fire given perfect perception, `dup_group` / `upi_pair` links.
"""

import datetime as dt
import io
import json
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from app.config import REPO_ROOT
from app.evaluation.synth import augment
from app.evaluation.synth.render import TEMPLATES
from app.pipeline.validate.gstin import ALPHABET, make_gstin

SEED = 20261008
EVAL_DATE = dt.date(2026, 10, 8)
EVAL_USER = "eval-user"
OUT = REPO_ROOT / "data" / "eval" / "fixtures"
PHOTO_AUGS = {"blur", "rotate", "perspective", "crumple"}

# --- fictional vendors -------------------------------------------------------------------------------
CITY_PIN = {
    "Mumbai": ("27", "400"),
    "Bengaluru": ("29", "560"),
    "Chennai": ("33", "600"),
    "Delhi": ("07", "110"),
    "Pune": ("27", "411"),
    "Hyderabad": ("36", "500"),
    "Kolkata": ("19", "700"),
    "Jaipur": ("08", "302"),
}
STATE = {
    "27": "Maharashtra",
    "29": "Karnataka",
    "33": "Tamil Nadu",
    "07": "Delhi",
    "36": "Telangana",
    "19": "West Bengal",
    "08": "Rajasthan",
}
RESTAURANTS = {
    "konkan": ("Konkan Thali House", "Mumbai", "Gokhale Road, Dadar West"),
    "malabar": ("Malabar Coast Kitchen", "Mumbai", "Kala Ghoda, Fort"),
    "bandrabean": ("Bandra Bean Co.", "Mumbai", "Chapel Road, Bandra West"),
    "chaiwala": ("Chaiwala Corner Pvt Ltd", "Mumbai", "Shop 4, Linking Road, Bandra West"),
    "saffron": ("Saffron Leaf Kitchen", "Bengaluru", "80 Feet Road, Indiranagar"),
    "coastal": ("Coastal Curry House", "Chennai", "12 Khader Nawaz Khan Road, Nungambakkam"),
    "tandoor": ("Tandoor Tales", "Delhi", "M-14 Connaught Circus"),
    "masala": ("Masala Junction", "Pune", "Fergusson College Road, Shivajinagar"),
    "biryani": ("Biryani Bay Restaurant", "Hyderabad", "Road No. 36, Jubilee Hills"),
    "hooghly": ("Hooghly Fish Kitchen", "Kolkata", "22 Park Street"),
    "rajwada": ("Rajwada Rasoi", "Jaipur", "MI Road, near Panch Batti"),
}
MENU = [
    ("Masala Dosa", 180),
    ("Paneer Tikka", 340),
    ("Veg Biryani", 290),
    ("Butter Naan", 60),
    ("Dal Makhani", 280),
    ("Filter Coffee", 90),
    ("Fresh Lime Soda", 110),
    ("Chicken Chettinad", 380),
    ("Gulab Jamun", 120),
    ("Veg Thali", 320),
    ("Fish Curry Meals", 420),
    ("Mango Lassi", 140),
    ("Hyderabadi Biryani", 360),
    ("Tandoori Roti", 40),
    ("Kadai Paneer", 310),
    ("Jeera Rice", 190),
    ("Prawn Fry", 460),
    ("Masala Chaas", 70),
]
HOTELS = {
    "harbour_mum": ("Harbourview Residency", "Mumbai", "Marine Drive, Churchgate", "HR"),
    "harbour_blr": ("Harbourview Residency", "Bengaluru", "14 Residency Road", "HR"),
    "lotus": ("Lotus Crest Hotel", "Pune", "Bund Garden Road", "LC"),
    "seabreeze": ("Seabreeze Suites", "Chennai", "ECR, Neelankarai", "SS"),
    "raisina": ("Raisina Court Hotel", "Delhi", "Janpath Lane", "RC"),
    "deccan": ("Deccan Pearl Hotel", "Hyderabad", "Banjara Hills Road No. 1", "DP"),
    "banyan": ("Banyan Court Inn", "Jaipur", "Civil Lines", "BC"),
    "parklane": ("Park Lane Rooms", "Kolkata", "Camac Street", "PL"),
}
STATIONERS = {
    "fort": ("Fort Stationery Mart", "Mumbai", "Perin Nariman Street, Fort"),
    "inkwell": ("Inkwell Stationers", "Delhi", "22 Nehru Place"),
    "quillmark": ("Quillmark Traders", "Bengaluru", "SP Road, Chickpet"),
    "papertrail": ("PaperTrail Office Supplies", "Kolkata", "Lalbazar Street, BBD Bagh"),
}
STATIONERY_ITEMS = [
    ("A4 Copier Paper 75 GSM (ream)", "4802", 250),
    ("Whiteboard Marker Set", "9608", 180),
    ("Box File, Lever Arch", "4820", 120),
    ("Stapler HD-45", "8472", 340),
    ("Printer Toner 88A", "8443", 2450),
    ("Sticky Notes 3x3 (pack)", "4820", 90),
    ("Gel Pens (box of 10)", "9608", 150),
    ("Whiteboard 4x3 ft", "9610", 2600),
    ("Desk Organiser", "3926", 420),
    ("Extension Board 4-way", "8536", 560),
]
FUEL_STATIONS = {
    "shivam": ("Shivam Fuel Point", "Pune", "Mumbai-Bengaluru Highway, Baner"),
    "greenmile": ("Green Mile Fuels", "Jaipur", "Tonk Road, Durgapura"),
    "highway": ("Highway Star Filling Station", "Chennai", "GST Road, Guindy"),
}
HANDWRITTEN = {
    "ganesh_tea": (
        "Shree Ganesh Tea Stall",
        "Pune",
        "Near Swargate Bus Stand",
        "meals",
        [("Cutting Chai", 15), ("Vada Pav", 25), ("Poha", 40)],
    ),
    "annapurna": (
        "Annapurna Bhojanalaya",
        "Jaipur",
        "Station Road",
        "meals",
        [("Thali", 230), ("Lassi", 60), ("Papad", 20)],
    ),
    "maatara": (
        "Maa Tara Tea Stall",
        "Kolkata",
        "Esplanade",
        "meals",
        [("Tea", 20), ("Egg Roll", 70), ("Ghugni", 50)],
    ),
    "srisai": (
        "Sri Sai Tiffins",
        "Hyderabad",
        "Ameerpet X Roads",
        "meals",
        [("Idli Vada", 60), ("Pesarattu", 80), ("Coffee", 30)],
    ),
    "omsai": (
        "Om Sai Fuel Centre",
        "Mumbai",
        "Sion-Panvel Highway, Chembur",
        "fuel",
        [("Petrol (Ltr)", 103)],
    ),
}
PEOPLE = ["A. Sharma", "R. Iyer", "P. Kulkarni", "S. Banerjee", "M. Reddy", "K. Mehta", "N. Joshi", "V. Nair"]
STEWARDS = ["Ramesh", "Anil", "Joseph", "Farhan", "Lakshmi", "Suresh"]
PLACES = {
    "Mumbai": [
        "Andheri East Metro",
        "Bandra Kurla Complex",
        "Lower Parel",
        "CSMT Airport T2",
        "Powai Lake Road",
        "Nariman Point",
    ],
    "Bengaluru": [
        "Whitefield ITPL",
        "MG Road Metro",
        "Koramangala 5th Block",
        "Kempegowda Airport",
        "Indiranagar 100 Ft Rd",
    ],
    "Chennai": [
        "Chennai Airport T1",
        "T. Nagar",
        "OMR Thoraipakkam",
        "Guindy Industrial Estate",
        "Anna Salai",
    ],
    "Delhi": ["Connaught Place", "Aerocity", "Nehru Place", "IGI Airport T3", "Saket District Centre"],
    "Pune": ["Hinjewadi Phase 1", "Koregaon Park", "Pune Station", "Viman Nagar", "Baner Road"],
    "Hyderabad": ["HITEC City", "Gachibowli", "Banjara Hills", "RGI Airport", "Begumpet"],
    "Kolkata": ["Salt Lake Sector V", "Park Street", "Howrah Station", "Netaji Subhas Airport", "New Town"],
    "Jaipur": ["Jaipur Junction", "Malviya Nagar", "C-Scheme", "Jaipur Airport", "Vaishali Nagar"],
}


# --- helpers ---------------------------------------------------------------------------------------------
def pan(rng: random.Random, entity: str = "C") -> str:
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return (
        "".join(rng.choice(letters) for _ in range(3))
        + entity
        + rng.choice(letters)
        + f"{rng.randint(1000, 9999)}"
        + rng.choice(letters)
    )


def gstin_for(rng: random.Random, city: str, valid: bool = True, entity: str = "C") -> str:
    g = make_gstin(CITY_PIN[city][0], pan(rng, entity))
    if valid:
        return g
    wrong = ALPHABET[(ALPHABET.index(g[-1]) + rng.randint(1, 35)) % 36]
    return g[:-1] + wrong


def pin(rng: random.Random, city: str) -> str:
    return f"{CITY_PIN[city][1]}{rng.randint(1, 99):03d}"


_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def words(n: int) -> str:
    """Indian-system number words (up to crores) for 'amount in words'."""

    def below_1000(x: int) -> str:
        out = []
        if x >= 100:
            out.append(f"{_ONES[x // 100]} hundred")
            x %= 100
        if x >= 20:
            out.append(_TENS[x // 10] + (f"-{_ONES[x % 10]}" if x % 10 else ""))
        elif x or not out:
            out.append(_ONES[x])
        return " ".join(out)

    parts = []
    for unit, size in (("crore", 10**7), ("lakh", 10**5), ("thousand", 1000)):
        if n >= size:
            parts.append(f"{below_1000(n // size)} {unit}")
            n %= size
    if n or not parts:
        parts.append(below_1000(n))
    return " ".join(parts)


def amount_words(x: float) -> str:
    rupees, paise = int(x), round((x - int(x)) * 100)
    s = f"Rupees {words(rupees).title()}"
    return s + (f" and {words(paise).title()} Paise Only" if paise else " Only")


@dataclass
class Fixture:
    id: str
    claim: str
    template: str
    doc: dict[str, Any]
    fields: dict[str, Any]
    items: list[dict[str, Any]] = field(default_factory=list)
    expected_rules: list[str] = field(default_factory=list)
    scenario: list[str] = field(default_factory=list)
    augment: list[str] = field(default_factory=list)
    dup_of: str | None = None
    dup_kind: str | None = None  # exact | rephoto
    decoy_of: str | None = None
    upi_pair: str | None = None
    file: str = ""
    raw_text: str = ""
    quality: str = "good"


def _base_fields(**kw: Any) -> dict[str, Any]:
    return {"currency": "INR", "upi_txn_id": None, "attendees_count": None, **kw}


def _payment(rng: random.Random, method: str) -> str:
    return {
        "card": f"CARD (VISA xx{rng.randint(1000, 9999)})",
        "upi": f"UPI Ref {rng.randint(10**11, 10**12 - 1)}",
        "cash": "CASH",
    }[method]


# --- per-template builders: (render doc, scored fields, items) ------------------------------------------
def build_restaurant(rng, key, date, covers, per_person, method="card", gstin="valid", show_covers=True):
    name, city, street = RESTAURANTS[key]
    target = covers * per_person / 1.05
    items, subtotal = [], 0
    for dish, price in rng.sample(MENU, len(MENU)):
        room = target * 1.02 - subtotal
        if room < price:
            continue
        qty = min(rng.randint(1, max(1, (covers + 1) // 2)), int(room // price))
        items.append(
            {
                "description": dish,
                "quantity": float(qty),
                "unit_price": float(price),
                "amount": float(qty * price),
            }
        )
        subtotal += qty * price
        if subtotal >= target * 0.97:
            break
    tax = 2 * round(subtotal * 0.025, 2)
    total = float(round(subtotal + tax))
    gst = gstin_for(rng, city, valid=gstin != "invalid") if gstin != "none" else None
    pay = _payment(rng, method)
    doc = {
        "vendor_print": name.upper(),
        "initials": "".join(w[0] for w in name.split()[:2]),
        "address": [street, f"{city} {pin(rng, city)}"],
        "phone": f"0{rng.randint(20, 80)}-{rng.randint(2000_0000, 6999_9999)}",
        "gstin_print": gst,
        "fssai": f"1{rng.randint(10**12, 10**13 - 1)}",
        "invoice_number": (
            f"{''.join(w[0] for w in name.split()[:2]).upper()}/{date:%y%m}/{rng.randint(1000, 9999)}"
        ),
        "date_print": date.strftime(rng.choice(["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"])),
        "time": f"{rng.randint(12, 22)}:{rng.randint(0, 59):02d}",
        "table": rng.randint(1, 30),
        "covers": covers if show_covers else None,
        "steward": rng.choice(STEWARDS),
        "items": items,
        "subtotal": float(subtotal),
        "tax_amount": tax,
        "gst_rate": 5,
        "round_off": round(total - subtotal - tax, 2),
        "total_amount": total,
        "payment_line": f"Paid by: {pay}",
    }
    names = [name, name.replace(" Pvt Ltd", "")] if "Pvt" in name else name
    fields = _base_fields(
        doc_type=["invoice", "receipt"],
        vendor_name=names,
        vendor_gstin=gst,
        invoice_number=doc["invoice_number"],
        date=date,
        subtotal=float(subtotal),
        tax_amount=tax,
        total_amount=total,
        payment_method=method,
        payee_name=None,
        city=city,
        category="meals",
        attendees_count=covers if show_covers else None,
    )
    if method == "upi":
        fields.pop("upi_txn_id")  # the bill prints a UPI ref; either reading is defensible
    return doc, fields, items


def build_ride(rng, city, date, total, method="card", toll=0.0):
    platform = float(rng.choice([15, 18, 21, 25]))
    fare = round((total - platform - toll) / 1.05, 2)
    tax = round(total - platform - toll - fare, 2)
    pickup, drop = rng.sample(PLACES[city], 2)
    h, pm, dur = rng.randint(7, 21), rng.randint(0, 59), rng.randint(18, 70)
    end = h * 60 + pm + dur
    gst = make_gstin(CITY_PIN[city][0], "AAJCR5521Q")
    doc = {
        "rider": rng.choice(PEOPLE).split(". ")[1],
        "product": rng.choice(["Go Mini", "Go Sedan", "Go Prime"]),
        "daypart": "morning" if h < 12 else "afternoon" if h < 17 else "evening",
        "date": date,
        "pickup_time": f"{h:02d}:{pm:02d}",
        "drop_time": f"{end // 60 % 24:02d}:{end % 60:02d}",
        "pickup": f"{pickup}, {city}",
        "drop": f"{drop}, {city}",
        "distance_km": round(rng.uniform(4, 38), 1),
        "duration_min": dur,
        "fare": fare,
        "toll": toll,
        "platform_fee": platform,
        "tax_amount": tax,
        "total_amount": float(total),
        "payment_print": {"card": f"Card xx{rng.randint(1000, 9999)}", "upi": "UPI (PayNow)", "cash": "Cash"}[
            method
        ],
        "invoice_number": f"RG-{STATE[CITY_PIN[city][0]][:2].upper()}-{rng.randint(100000, 999999)}",
        "gstin_print": gst,
    }
    fields = _base_fields(
        doc_type=["ride_receipt", "receipt", "invoice"],
        vendor_name=["RydeGo", "RydeGo Mobility Pvt Ltd", "RydeGo Mobility"],
        vendor_gstin=gst,
        invoice_number=doc["invoice_number"],
        date=date,
        tax_amount=tax,
        total_amount=float(total),
        payment_method=method,
        payee_name=None,
        city=city,
        category="travel_local",
    )
    return doc, fields, []


def build_fuel(rng, key, date, total, method="card", gstin=True):
    name, city, street = FUEL_STATIONS[key]
    product, rate = rng.choice([("PETROL", 103.44), ("DIESEL", 90.03), ("XTRA PREMIUM", 111.20)])
    gst = gstin_for(rng, city, entity="F") if gstin else None
    doc = {
        "vendor_print": name.upper(),
        "address": [street, f"{city} - {pin(rng, city)}"],
        "gstin_print": gst,
        "invoice_number": f"{rng.randint(10000, 99999)}",
        "date_print": date.strftime(rng.choice(["%d/%m/%Y", "%d-%b-%Y"])).upper(),
        "time": f"{rng.randint(6, 22):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}",
        "product": product,
        "rate": rate,
        "litres": round(total / rate, 2),
        "total_amount": float(total),
        "vehicle": (
            f"{STATE[CITY_PIN[city][0]][:2].upper()}{rng.randint(1, 50):02d}"
            f"{rng.choice('ABCDEFGH')}{rng.choice('ABCDEFGH')}{rng.randint(1000, 9999)}"
        ),
        "payment_print": {"card": "CARD", "upi": "UPI", "cash": "CASH"}[method],
    }
    fields = _base_fields(
        doc_type=["fuel", "receipt"],
        vendor_name=name,
        vendor_gstin=gst,
        invoice_number=doc["invoice_number"],
        date=date,
        subtotal=None,
        tax_amount=None,
        total_amount=float(total),
        payment_method=method,
        payee_name=None,
        city=city,
        category="fuel",
    )
    return doc, fields, []


def build_hotel(rng, key, date, nights, tariff, method="card", upi_ref=None, legal_name=None):
    name, city, street, initials = HOTELS[key]
    rate = 12 if tariff <= 7500 else 18
    arrival = date - dt.timedelta(days=nights)
    nights_list = [
        {
            "date": arrival + dt.timedelta(days=i),
            "tariff": float(tariff),
            "cgst": round(tariff * rate / 200, 2),
        }
        for i in range(nights)
    ]
    subtotal = float(tariff * nights)
    tax = round(subtotal * rate / 100, 2)
    total = round(subtotal + tax, 2)
    gst = gstin_for(rng, city, entity="F" if rng.random() < 0.4 else "C")
    if method == "upi":
        pay = f"UPI (PayNow) Ref {upi_ref}" if upi_ref else "UPI (PayNow)"
    else:
        pay = {"card": f"Credit Card xx{rng.randint(1000, 9999)}", "cash": "Cash"}[method]
    doc = {
        "vendor_print": name.upper(),
        "unit_of": legal_name,
        "initials": initials,
        "address": [
            f"{street}, {city} {pin(rng, city)}",
            f"Tel: +91 {rng.randint(70000, 99999)} {rng.randint(10000, 99999)}",
        ],
        "gstin_print": gst,
        "invoice_number": f"{initials}-{rng.randint(10000, 99999)}",
        "date_print": date.strftime("%d/%m/%Y"),
        "arrival_print": arrival.strftime("%d/%m/%Y"),
        "guest": rng.choice(PEOPLE),
        "room": rng.randint(101, 920),
        "room_type": rng.choice(["Deluxe", "Executive", "Superior"]),
        "company": "Acme India Pvt Ltd",
        "nights": nights,
        "nights_list": nights_list,
        "subtotal": subtotal,
        "tax_amount": tax,
        "gst_rate": rate,
        "total_amount": total,
        "payment_print": pay,
    }
    vname = [name, legal_name] if legal_name else name
    fields = _base_fields(
        doc_type=["hotel_folio", "invoice"],
        vendor_name=vname,
        vendor_gstin=gst,
        invoice_number=doc["invoice_number"],
        date=date,
        subtotal=subtotal,
        tax_amount=tax,
        total_amount=total,
        payment_method=method,
        payee_name=None,
        city=city,
        category="lodging",
    )
    if upi_ref:
        fields.pop("upi_txn_id")
    return doc, fields, []


def build_stationery(rng, key, date, n_items, target, method="card", gstin="valid"):
    name, city, street = STATIONERS[key]
    picks = rng.sample(STATIONERY_ITEMS, n_items)
    items, subtotal = [], 0
    for i, (desc, hsn, price) in enumerate(picks):
        remaining = target / 1.18 - subtotal
        qty = (
            max(1, round(remaining / price / (n_items - i)))
            if i < n_items - 1
            else max(1, round(remaining / price))
        )
        items.append(
            {
                "description": desc,
                "hsn": hsn,
                "quantity": float(qty),
                "unit_price": float(price),
                "amount": float(qty * price),
            }
        )
        subtotal += qty * price
    tax = round(subtotal * 0.18, 2)
    total = round(subtotal + tax, 2)
    gst = gstin_for(rng, city, valid=gstin != "invalid", entity="F") if gstin != "none" else None
    doc = {
        "vendor_print": name.upper(),
        "address": [
            street,
            f"{city} {pin(rng, city)}  |  Ph {rng.randint(70000, 99999)}{rng.randint(10000, 99999)}",
        ],
        "gstin_print": gst,
        "invoice_number": (
            f"{name.split()[0][:3].upper()}/{date:%y}-{date.year % 100 + 1}/{rng.randint(100, 2999)}"
        ),
        "date_print": date.strftime("%d/%m/%Y"),
        "buyer": "Acme India Pvt Ltd (walk-in)",
        "state": f"{STATE[CITY_PIN[city][0]]} ({CITY_PIN[city][0]})",
        "items": items,
        "subtotal": float(subtotal),
        "tax_amount": tax,
        "gst_rate": 18,
        "total_amount": total,
        "amount_words": amount_words(total),
        "payment_print": {"card": "Card", "upi": "UPI", "cash": "Cash"}[method],
    }
    fields = _base_fields(
        doc_type=["invoice", "receipt"],
        vendor_name=name,
        vendor_gstin=gst,
        invoice_number=doc["invoice_number"],
        date=date,
        subtotal=float(subtotal),
        tax_amount=tax,
        total_amount=total,
        payment_method=method,
        payee_name=None,
        city=city,
        category="office",
    )
    return doc, fields, [{k: v for k, v in it.items() if k != "hsn"} for it in items]


def build_upi(rng, payee, date, total, txn_id=None):
    txn = txn_id or f"{rng.randint(10**11, 10**12 - 1)}"
    h, m = rng.randint(8, 22), rng.randint(0, 59)
    slug = "".join(ch for ch in payee.lower() if ch.isalnum())[:14]
    doc = {
        "status_time": f"{h % 12 or 12}:{m:02d}",
        "total_amount": float(total),
        "datetime_print": f"{date:%d %b %Y}, {h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}",
        "payee_print": payee,
        "payee_vpa": f"{slug}@paynow",
        "payer": f"{rng.choice(PEOPLE)} (xx{rng.randint(1000, 9999)})",
        "upi_txn_id": txn,
        "app_txn_id": (
            f"PN{date:%y%m%d}{h:02d}{m:02d}"
            f"{rng.choice('ABCDEFGHJK')}{rng.choice('LMNPQRSTUV')}{rng.randint(10, 99)}"
        ),
        "note": rng.choice([None, "Hotel stay", "Bill payment", None]),
    }
    fields = {
        "doc_type": "upi_screenshot",
        "vendor_gstin": None,
        "date": date,
        "currency": "INR",
        "subtotal": None,
        "tax_amount": None,
        "total_amount": float(total),
        "payment_method": "upi",
        "upi_txn_id": txn,
        "payee_name": payee,
        "attendees_count": None,
    }
    return doc, fields, []


def build_handwritten(rng, key, date, smudge=False, show_date=True, lines=None):
    """`lines`: optional fixed (description, qty, unit price) rows instead of random menu picks."""
    name, city, street, category, menu = HANDWRITTEN[key]
    rows = lines or [(desc, rng.randint(1, 3), price) for desc, price in menu]
    items = [
        {"description": d, "quantity": float(q), "unit_price": float(p), "amount": float(q * p)}
        for d, q, p in rows
    ]
    total = float(sum(i["amount"] for i in items))
    doc = {
        "vendor_print": name.upper(),
        "address": [f"{street}, {city}"],
        "invoice_number": f"{rng.randint(101, 999)}",
        "date_hand": f"{date.day}/{date.month}/{date:%y}" if show_date else None,
        "customer": rng.choice(["Acme India", "Mr. Sharma", "Office", None]),
        "items": items,
        "total_amount": total,
        "payment_hand": rng.choice(["Paid cash", "Cash recd.", "Recd with thanks"]),
        "smudge_date": smudge,
    }
    fields = _base_fields(
        doc_type=["handwritten", "receipt", "invoice"],
        vendor_name=name,
        vendor_gstin=None,
        invoice_number=doc["invoice_number"],
        date=None if (smudge or not show_date) else date,
        subtotal=None,
        tax_amount=None,
        total_amount=total,
        payment_method="cash",
        payee_name=None,
        city=city,
        category=category,
    )
    return doc, fields, items


# --- the planted scenario --------------------------------------------------------------------------------
D = dt.date
CLAIMS = [
    ("eval_c01", "Mumbai client visit", True),
    ("eval_c02", "Bengaluru sales review", True),
    ("eval_c03", "Pune plant audit", False),
    ("eval_c04", "Chennai vendor meeting", False),
    ("eval_c05", "Delhi conference", False),
    ("eval_c06", "Hyderabad training", False),
    ("eval_c07", "Jaipur site visit", False),
    ("eval_c08", "Mumbai quarterly review", False),
    ("eval_c09", "Kolkata distributor meet", False),
    ("eval_c10", "Bengaluru offsite", False),
    ("eval_c11", "Chennai follow-up", False),
    ("eval_c12", "Hyderabad review", False),
]


def plan() -> list[Fixture]:
    """Every receipt with its claim, scenario tags and expected rule ids (hand-labelled, oracle-verified)."""
    fx: list[Fixture] = []

    def add(claim: str, template: str, built, rules=(), scenario=(), **kw) -> Fixture:
        doc, fields, items = built
        f = Fixture(
            f"fx_{len(fx) + 1:03d}", claim, template, doc, fields, items, list(rules), list(scenario), **kw
        )
        fx.append(f)
        return f

    def r(i: int) -> random.Random:
        return random.Random(f"{SEED}:{i}")

    def upi_for(claim: str, inv: Fixture, payee: str | None = None, txn: str | None = None, **kw) -> Fixture:
        payee = payee or (
            inv.fields["vendor_name"][0]
            if isinstance(inv.fields["vendor_name"], list)
            else inv.fields["vendor_name"]
        )
        u = add(
            claim,
            "upi",
            build_upi(r(len(fx) + 1), payee, inv.fields["date"], inv.fields["total_amount"], txn),
            scenario=["upi_pair"],
            **kw,
        )
        u.upi_pair, inv.upi_pair = inv.id, u.id
        inv.scenario.append("upi_pair")
        return u

    def dup(claim: str, orig: Fixture, kind: str) -> Fixture:
        f = Fixture(
            f"fx_{len(fx) + 1:03d}",
            claim,
            orig.template,
            orig.doc,
            dict(orig.fields),
            orig.items,
            list(orig.expected_rules),
            [f"dup_{kind}"],
            dup_of=orig.id,
            dup_kind=kind,
        )
        fx.append(f)
        return f

    c = "eval_c01"
    f1 = add(c, "restaurant", build_restaurant(r(1), "chaiwala", D(2026, 9, 15), 2, 690))
    f2 = add(c, "ride", build_ride(r(2), "Mumbai", D(2026, 9, 15), 486, "upi"))
    f3 = add(c, "hotel", build_hotel(r(3), "harbour_mum", D(2026, 9, 16), 1, 4800, "upi"))
    upi_for(c, f3)
    add(
        c,
        "restaurant",
        build_restaurant(r(5), "chaiwala", D(2026, 9, 16), 3, 940),
        ["MEALS_CAP_PER_PERSON"],
        ["meals_cap"],
    )

    c = "eval_c02"
    f6 = add(c, "ride", build_ride(r(6), "Bengaluru", D(2026, 9, 17), 612))
    add(c, "ride", build_ride(r(7), "Bengaluru", D(2026, 9, 17), 380), scenario=["decoy"], decoy_of=f6.id)
    add(
        c,
        "stationery",
        build_stationery(r(8), "quillmark", D(2026, 9, 17), 3, 6490, "cash", "invalid"),
        ["GST_INVOICE_ABOVE_5000", "CASH_ABOVE_2000_JUSTIFY"],
        ["invalid_gstin", "gst_block", "cash"],
    )
    dup(c, f2, "exact")

    c = "eval_c03"
    f10 = add(c, "hotel", build_hotel(r(10), "lotus", D(2026, 9, 23), 2, 2600))
    f11 = add(
        c,
        "restaurant",
        build_restaurant(r(11), "masala", D(2026, 9, 22), 4, 590, gstin="invalid"),
        scenario=["invalid_gstin"],
    )
    add(c, "fuel", build_fuel(r(12), "shivam", D(2026, 9, 22), 2000, "upi"))
    add(c, "handwritten", build_handwritten(r(13), "ganesh_tea", D(2026, 9, 21)))
    dup(c, f1, "rephoto")

    c = "eval_c04"
    f15 = add(
        c,
        "restaurant",
        build_restaurant(r(15), "coastal", D(2026, 9, 22), 2, 980),
        ["MEALS_CAP_PER_PERSON"],
        ["meals_cap"],
    )
    f16 = add(
        c,
        "hotel",
        build_hotel(r(16), "seabreeze", D(2026, 9, 23), 1, 7000, "upi"),
        ["LODGING_CAP_METRO"],
        ["lodging_cap"],
    )
    upi_for(c, f16)
    f18 = add(
        c,
        "ride",
        build_ride(r(18), "Chennai", D(2026, 9, 23), 1850, toll=120.0),
        ["LOCAL_TRAVEL_DAILY_CAP"],
        ["local_travel_cap"],
    )
    dup(c, f11, "exact")

    c = "eval_c05"
    add(
        c,
        "restaurant",
        build_restaurant(r(20), "tandoor", D(2026, 9, 24), 2, 620, gstin="none"),
        scenario=["missing_gstin"],
    )
    f21 = add(
        c,
        "stationery",
        build_stationery(r(21), "inkwell", D(2026, 9, 26), 3, 3540),
        ["OFFICE_SUPPLIES_WEEKEND"],
        ["weekend"],
    )
    f22 = add(
        c,
        "hotel",
        build_hotel(r(22), "raisina", D(2026, 9, 26), 2, 5500, "upi"),
        ["LODGING_CAP_METRO"],
        ["lodging_cap"],
    )
    upi_for(c, f22)
    dup(c, f10, "rephoto")

    c = "eval_c06"
    add(c, "restaurant", build_restaurant(r(25), "biryani", D(2026, 9, 28), 3, 700))
    f26 = add(c, "ride", build_ride(r(26), "Hyderabad", D(2026, 9, 28), 540, "upi"))
    txn = f"{r(28).randint(10**11, 10**12 - 1)}"
    f28 = add(
        c,
        "hotel",
        build_hotel(
            r(28), "deccan", D(2026, 9, 29), 1, 3900, "upi", upi_ref=txn, legal_name="DPH Hospitality LLP"
        ),
    )
    upi_for(c, f28, payee="DPH HOSPITALITY", txn=txn).scenario.append("upi_txn_link")

    c = "eval_c07"
    f30 = add(
        c,
        "hotel",
        build_hotel(r(30), "banyan", D(2026, 10, 1), 2, 2400),
        ["LODGING_CAP_NON_METRO"],
        ["lodging_cap"],
    )
    add(
        c,
        "handwritten",
        build_handwritten(r(31), "annapurna", D(2026, 9, 30), show_date=False),
        scenario=["missing_date"],
    )
    add(c, "fuel", build_fuel(r(32), "greenmile", D(2026, 9, 30), 5400), ["FUEL_CAP_PER_CLAIM"], ["fuel_cap"])
    add(c, "restaurant", build_restaurant(r(33), "rajwada", D(2026, 9, 30), 2, 560, "upi"))
    dup(c, f15, "exact")

    c = "eval_c08"
    f35 = add(
        c,
        "restaurant",
        build_restaurant(r(35), "chaiwala", D(2026, 10, 1), 3, 520),
        scenario=["decoy"],
        decoy_of=f1.id,
    )
    f36 = add(c, "ride", build_ride(r(36), "Mumbai", D(2026, 10, 2), 720, "upi"))
    add(
        c,
        "hotel",
        build_hotel(r(37), "harbour_mum", D(2026, 8, 27), 1, 5000),
        ["SUBMISSION_WINDOW_30D"],
        ["late"],
        decoy_of=f3.id,
    )
    upi_for(c, f36)
    dup(c, f18, "rephoto")

    c = "eval_c09"
    f40 = add(
        c,
        "restaurant",
        build_restaurant(r(40), "hooghly", D(2026, 10, 5), 4, 975),
        ["MEALS_CAP_PER_PERSON"],
        ["meals_cap"],
    )
    f41 = add(c, "hotel", build_hotel(r(41), "parklane", D(2026, 10, 5), 1, 4200, "upi"))
    upi_for(c, f41)
    f43 = add(
        c,
        "stationery",
        build_stationery(r(43), "papertrail", D(2026, 10, 5), 2, 1180, gstin="invalid"),
        scenario=["invalid_gstin"],
    )
    add(c, "handwritten", build_handwritten(r(44), "maatara", D(2026, 10, 5)))
    dup(c, f21, "exact")

    c = "eval_c10"
    f46 = add(c, "restaurant", build_restaurant(r(46), "saffron", D(2026, 10, 6), 6, 700))
    add(c, "ride", build_ride(r(47), "Bengaluru", D(2026, 10, 6), 890, "upi"))
    f48 = add(
        c,
        "hotel",
        build_hotel(r(48), "harbour_blr", D(2026, 10, 6), 1, 5200, "upi"),
        scenario=["decoy"],
        decoy_of=f3.id,
    )
    upi_for(c, f48)
    add(
        c,
        "restaurant",
        build_restaurant(r(50), "saffron", D(2026, 10, 5), 1, 640, show_covers=False),
        scenario=["missing_covers"],
    )
    dup(c, f26, "exact")
    dup(c, f40, "rephoto")

    c = "eval_c11"
    f53 = add(
        c,
        "restaurant",
        build_restaurant(r(53), "coastal", D(2026, 10, 7), 2, 575, "upi"),
        scenario=["decoy"],
        decoy_of=f15.id,
    )
    upi_for(c, f53)
    add(
        c,
        "fuel",
        build_fuel(r(55), "highway", D(2026, 10, 7), 1500, "cash", gstin=False),
        scenario=["missing_gstin"],
    )
    dup(c, f30, "exact")
    dup(c, f43, "exact")
    dup(c, f46, "rephoto")

    c = "eval_c12"
    add(c, "ride", build_ride(r(59), "Hyderabad", D(2026, 10, 7), 1050))
    add(
        c,
        "handwritten",
        build_handwritten(r(60), "srisai", D(2026, 10, 7), smudge=True),
        scenario=["missing_date", "smudged"],
    )
    dup(c, f35, "exact")
    dup(c, f36, "rephoto")
    return fx


def _augmentations(f: Fixture, rng: random.Random) -> list[str]:
    if f.dup_kind == "rephoto":
        return ["crop", "perspective", rng.choice(["rotate", "crumple"]), "jpeg"]
    if f.template == "upi":
        return rng.choice([[], [], ["jpeg"]])
    return rng.choice(
        [
            [],
            [],
            ["crumple"],
            ["rotate"],
            ["blur"],
            ["perspective", "crumple"],
            ["rotate", "jpeg"],
            ["blur", "crumple"],
        ]
    )


def _encode(img: Image.Image, photo: bool) -> tuple[bytes, str]:
    buf = io.BytesIO()
    if photo:  # phone photos are JPEGs; keeps the committed set small
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue(), ".jpg"
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), ".png"


def _jsonable(v: Any) -> Any:
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def generate(out: Path = OUT) -> list[dict[str, Any]]:
    fixtures = plan()
    by_id = {f.id: f for f in fixtures}
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rendered: dict[str, Image.Image] = {}
    rows = []
    for f in fixtures:
        rng = random.Random(f"{SEED}:render:{f.id}")
        if f.dup_kind == "exact":
            orig = by_id[f.dup_of]  # type: ignore[index]
            f.file, f.raw_text, f.augment, f.quality = (
                f"{f.id}{Path(orig.file).suffix}",
                orig.raw_text,
                orig.augment,
                orig.quality,
            )
            shutil.copyfile(out / orig.file, out / f.file)
        else:
            source = by_id[f.dup_of] if f.dup_of else f  # type: ignore[index]
            if source.id in rendered:
                clean = rendered[source.id]
                lines = source.raw_text.split("\n")
            else:
                clean, lines = TEMPLATES[f.template](f.doc, rng)
            rendered.setdefault(source.id, clean)
            f.raw_text = "\n".join(lines)
            f.augment = _augmentations(f, rng)
            img = augment.apply(clean, f.augment, rng)
            data, ext = _encode(img, bool(PHOTO_AUGS & set(f.augment)))
            f.file = f"{f.id}{ext}"
            (out / f.file).write_bytes(data)
            f.quality = (
                "handwritten"
                if f.template == "handwritten"
                else "blurry"
                if "blur" in f.augment
                else "rotated"
                if "rotate" in f.augment
                else "good"
            )
        rows.append(
            {
                "id": f.id,
                "file": f.file,
                "claim_id": f.claim,
                "template": f.template,
                "scenario": f.scenario,
                "augment": f.augment,
                "fields": {k: _jsonable(v) for k, v in f.fields.items()},
                "items": f.items,
                "raw_text": f.raw_text,
                "quality": f.quality,
                "expected_rules": sorted(f.expected_rules),
                "dup_group": f"dg_{f.dup_of or f.id}"
                if f.dup_of or any(g.dup_of == f.id for g in fixtures)
                else None,
                "dup_kind": f.dup_kind,
                "dup_of": f.dup_of,
                "decoy_of": f.decoy_of,
                "upi_pair": f.upi_pair,
            }
        )
    with (out / "ground_truth.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    claims = [
        {
            "id": cid,
            "title": title,
            "smoke": smoke,
            "fixtures": [r["id"] for r in rows if r["claim_id"] == cid],
        }
        for cid, title, smoke in CLAIMS
    ]
    tags = [t for r in rows for t in r["scenario"]]
    manifest = {
        "seed": SEED,
        "eval_date": EVAL_DATE.isoformat(),
        "user_id": EVAL_USER,
        "ruleset": "acme_v1.json",
        "n_receipts": len(rows),
        "claims": claims,
        "counts": {t: tags.count(t) for t in sorted(set(tags))},
        "note": "Synthetic: every vendor, person, GSTIN and UPI id is fictional.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return rows


def main() -> None:
    rows = generate()
    print(f"wrote {len(rows)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
