"""Pillow templates for synthetic Indian expense documents. Each template draws a `Doc` and returns its text.

Fonts are macOS system fonts with a Pillow fallback; the committed fixtures were rendered on macOS.
shortcut: elsewhere the fallback font changes pixels (not ground truth); vendor fonts if CI must regenerate.
"""

import random
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_SYS = Path("/System/Library/Fonts")
_SUP = _SYS / "Supplemental"
FONTS = {
    "mono": [_SUP / "Courier New.ttf", _SUP / "Andale Mono.ttf"],
    "mono_bold": [_SUP / "Courier New Bold.ttf", _SUP / "Courier New.ttf"],
    "sans": [_SUP / "Arial.ttf", _SYS / "Helvetica.ttc"],
    "sans_bold": [_SUP / "Arial Bold.ttf", _SUP / "Arial.ttf"],
    "narrow": [_SUP / "Arial Narrow.ttf", _SUP / "Arial.ttf"],
    "serif": [_SUP / "Georgia.ttf", _SYS / "Times.ttc"],
    "serif_bold": [_SUP / "Georgia Bold.ttf", _SUP / "Georgia.ttf"],
    "hand": [_SUP / "Bradley Hand Bold.ttf", _SYS / "Noteworthy.ttc"],
    "unicode": [_SYS / "Kohinoor.ttc", _SYS / "Helvetica.ttc"],
}
INK = (28, 28, 30)


@cache
def font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS[kind]:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def inr(x: float, decimals: int = 2) -> str:
    """Indian digit grouping: 123456.5 -> 1,23,456.50."""
    neg, x = x < 0, abs(x)
    whole, frac = f"{x:.{decimals}f}".split(".") if decimals else (f"{x:.0f}", "")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    out = ",".join([*groups, tail]) if groups else tail
    return ("-" if neg else "") + out + (f".{frac}" if decimals else "")


@dataclass
class Paper:
    """A strip of paper that grows downwards; records every printed line as transcript text."""

    width: int
    bg: tuple[int, int, int] = (250, 249, 244)
    margin: int = 28
    y: int = 30
    ops: list[tuple[str, tuple]] = field(default_factory=list)
    text: list[str] = field(default_factory=list)

    def gap(self, h: int = 10) -> None:
        self.y += h

    def line(
        self, s: str, kind: str = "mono", size: int = 20, align: str = "l", ink=INK, record=True
    ) -> None:
        self.ops.append(("text", (s, kind, size, align, self.y, ink)))
        if record:
            self.text.append(s)
        self.y += int(size * 1.32)

    def lr(self, left: str, right: str, kind: str = "mono", size: int = 20, ink=INK) -> None:
        self.ops.append(("lr", (left, right, kind, size, self.y, ink)))
        self.text.append(f"{left}  {right}")
        self.y += int(size * 1.32)

    def cols(self, cells: list[tuple[str, float, str]], kind: str = "mono", size: int = 18, ink=INK) -> None:
        """cells: (text, x as fraction of width, align l|r)."""
        self.ops.append(("cols", (cells, kind, size, self.y, ink)))
        self.text.append("  ".join(c[0] for c in cells))
        self.y += int(size * 1.32)

    def rule(self, dashed: bool = True, weight: int = 1) -> None:
        self.ops.append(("rule", (self.y + 6, dashed, weight)))
        self.y += 14

    def box(self, x0: float, y0: int, x1: float, y1: int, fill=None, outline=INK, radius: int = 0) -> None:
        self.ops.append(("box", (x0, y0, x1, y1, fill, outline, radius)))

    def render(self, height: int | None = None) -> Image.Image:
        img = Image.new("RGB", (self.width, height or self.y + 40), self.bg)
        d = ImageDraw.Draw(img)
        m, w = self.margin, self.width
        for op, a in self.ops:
            if op == "text":
                s, kind, size, align, y, ink = a
                f = font(kind, size)
                tw = d.textlength(s, font=f)
                x = {"l": m, "c": (w - tw) / 2, "r": w - m - tw}[align]
                d.text((x, y), s, fill=ink, font=f)
            elif op == "lr":
                left, right, kind, size, y, ink = a
                f = font(kind, size)
                d.text((m, y), left, fill=ink, font=f)
                d.text((w - m - d.textlength(right, font=f), y), right, fill=ink, font=f)
            elif op == "cols":
                cells, kind, size, y, ink = a
                f = font(kind, size)
                for s, fx, al in cells:
                    x = fx * w - (d.textlength(s, font=f) if al == "r" else 0)
                    d.text((x, y), s, fill=ink, font=f)
            elif op == "rule":
                y, dashed, weight = a
                if dashed:
                    for x in range(m, w - m, 12):
                        d.line((x, y, min(x + 6, w - m), y), fill=(90, 90, 90), width=weight)
                else:
                    d.line((m, y, w - m, y), fill=(60, 60, 60), width=weight)
            elif op == "ellipse":
                cx, cy, r, colour = a
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
            elif op == "check":
                cx, cy, r, colour = a
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
                d.line((cx - 32, cy + 2, cx - 8, cy + 26, cx + 34, cy - 24), fill=(255, 255, 255), width=12)
            elif op == "box":
                x0, y0, x1, y1, fill, outline, radius = a
                d.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill, outline=outline, width=2)
        return img


def _emblem(p: Paper, initials: str, rng: random.Random, kind: str = "serif_bold") -> None:
    """A simple text-mark logo: initials in a ring, centred."""
    r = 34
    cx = p.width // 2
    p.ops.append(("ellipse", (cx, p.y + r, r, rng.choice([(150, 40, 30), (30, 70, 120), (40, 100, 60)]))))
    p.ops.append(("text", (initials, kind, 30, "c", p.y + r - 19, (250, 249, 244))))
    p.y += 2 * r + 10


Doc = dict[str, Any]


def _fmt_date(d, style: str) -> str:
    return {
        "dmy": d.strftime("%d/%m/%Y"),
        "dmy-": d.strftime("%d-%m-%Y"),
        "dby": d.strftime("%d %b %Y"),
        "dmy2": d.strftime("%d/%m/%y"),
        "dby-": d.strftime("%d-%b-%Y"),
    }[style]


# --- templates ----------------------------------------------------------------------------------------


def restaurant(doc: Doc, rng: random.Random) -> tuple[Image.Image, list[str]]:
    p = Paper(width=rng.choice([600, 620, 640]))
    if rng.random() < 0.5:
        _emblem(p, doc["initials"], rng)
    p.line(doc["vendor_print"], "mono_bold", 30, "c")
    for a in doc["address"]:
        p.line(a, "mono", 18, "c")
    p.line(f"Ph: {doc['phone']}", "mono", 18, "c")
    if doc.get("gstin_print"):
        p.line(f"GSTIN: {doc['gstin_print']}", "mono", 19, "c")
    p.line(f"FSSAI Lic No: {doc['fssai']}", "mono", 16, "c")
    p.gap(4)
    p.line("TAX INVOICE", "mono_bold", 22, "c")
    p.rule()
    p.lr(f"Bill No: {doc['invoice_number']}", f"Date: {doc['date_print']}", size=18)
    covers = f"Covers: {doc['covers']}" if doc.get("covers") else "Order: Dine-in"
    p.lr(f"Table: {doc['table']}  {covers}", f"Time: {doc['time']}", size=18)
    p.lr(f"Steward: {doc['steward']}", "", size=18)
    p.rule()
    p.cols([("Item", 0.05, "l"), ("Qty", 0.6, "r"), ("Rate", 0.76, "r"), ("Amount", 0.955, "r")], "mono_bold")
    p.rule()
    for it in doc["items"]:
        p.cols(
            [
                (it["description"][:22], 0.05, "l"),
                (str(int(it["quantity"])), 0.6, "r"),
                (inr(it["unit_price"]), 0.76, "r"),
                (inr(it["amount"]), 0.955, "r"),
            ]
        )
    p.rule()
    p.lr("Sub Total", inr(doc["subtotal"]))
    if doc.get("service_charge"):
        p.lr("Service Charge (optional)", inr(doc["service_charge"]))
    half = doc["tax_amount"] / 2
    p.lr(f"CGST @ {doc['gst_rate'] / 2:g}%", inr(half))
    p.lr(f"SGST @ {doc['gst_rate'] / 2:g}%", inr(half))
    if doc.get("round_off"):
        p.lr("Round Off", f"{doc['round_off']:+.2f}")
    p.rule(dashed=False, weight=2)
    p.lr("GRAND TOTAL Rs.", inr(doc["total_amount"]), "mono_bold", 24)
    p.rule(dashed=False, weight=2)
    p.line(doc["payment_line"], "mono", 18)
    p.gap(6)
    p.line("Thank you! Please visit again", "mono", 17, "c")
    p.line("** Prices inclusive of packing **", "mono", 15, "c")
    return p.render(), p.text


def ride(doc: Doc, rng: random.Random) -> tuple[Image.Image, list[str]]:
    p = Paper(width=720, bg=(255, 255, 255), margin=44)
    green = (14, 122, 84)
    p.ops.append(("box", (0, 0, 720, 96, green, green, 0)))
    p.ops.append(("text", ("RydeGo", "sans_bold", 40, "l", 22, (255, 255, 255))))
    p.text.append("RydeGo")
    p.y = 120
    p.line(f"Thanks for riding, {doc['rider']}", "sans_bold", 26)
    p.line(f"We hope you enjoyed your {doc['product']} ride this {doc['daypart']}.", "sans", 19)
    p.gap(10)
    p.lr("Total", f"Rs. {inr(doc['total_amount'])}", "sans_bold", 34)
    p.line(_fmt_date(doc["date"], "dby"), "sans", 19, ink=(90, 90, 90))
    p.rule(dashed=False)
    p.line("Trip details", "sans_bold", 21)
    p.line(f"{doc['pickup_time']}   {doc['pickup']}", "sans", 18)
    p.line(f"{doc['drop_time']}   {doc['drop']}", "sans", 18)
    p.line(
        f"{doc['distance_km']:.1f} km  |  {doc['duration_min']} min  |  {doc['product']}",
        "sans",
        17,
        ink=(90, 90, 90),
    )
    p.rule(dashed=False)
    p.line("Fare breakdown", "sans_bold", 21)
    p.lr("Trip fare", inr(doc["fare"]), "sans", 19)
    if doc.get("toll"):
        p.lr("Tolls & parking", inr(doc["toll"]), "sans", 19)
    p.lr("Platform fee", inr(doc["platform_fee"]), "sans", 19)
    p.lr("GST @ 5% on trip fare", inr(doc["tax_amount"]), "sans", 19)
    p.rule(dashed=False)
    p.lr("Amount paid", f"Rs. {inr(doc['total_amount'])}", "sans_bold", 22)
    p.lr("Payment", doc["payment_print"], "sans", 19)
    p.gap(16)
    p.line(f"Invoice No: {doc['invoice_number']}", "sans", 16, ink=(110, 110, 110))
    p.line(f"RydeGo Mobility Pvt Ltd  |  GSTIN {doc['gstin_print']}", "sans", 16, ink=(110, 110, 110))
    p.line("This is a computer generated invoice.", "sans", 15, ink=(130, 130, 130))
    return p.render(), p.text


def fuel(doc: Doc, rng: random.Random) -> tuple[Image.Image, list[str]]:
    p = Paper(width=rng.choice([470, 500]), margin=22, bg=(246, 244, 236))
    p.line("*** WELCOME ***", "mono_bold", 20, "c")
    p.line(doc["vendor_print"], "mono_bold", 23, "c")
    for a in doc["address"]:
        p.line(a, "mono", 16, "c")
    if doc.get("gstin_print"):
        p.line(f"GSTIN:{doc['gstin_print']}", "mono", 16, "c")
    p.rule()
    p.lr("RCPT NO:", doc["invoice_number"], size=18)
    p.lr("DATE:", doc["date_print"], size=18)
    p.lr("TIME:", doc["time"], size=18)
    p.lr("FP ID / NOZZLE:", f"{rng.randint(1, 8):02d} / {rng.randint(1, 4)}", size=18)
    p.lr("PRODUCT:", doc["product"], size=18)
    p.lr("RATE (Rs/L):", f"{doc['rate']:.2f}", size=18)
    p.lr("VOLUME (L):", f"{doc['litres']:.2f}", size=18)
    p.rule()
    p.lr("AMOUNT (Rs):", inr(doc["total_amount"]), "mono_bold", 22)
    p.rule()
    p.lr("VEHICLE NO:", doc["vehicle"], size=18)
    p.lr("MODE:", doc["payment_print"], size=18)
    p.gap(6)
    p.line("SAVE FUEL  SAVE MONEY", "mono", 16, "c")
    p.line("THANK YOU - VISIT AGAIN", "mono", 16, "c")
    return p.render(), p.text


def hotel(doc: Doc, rng: random.Random) -> tuple[Image.Image, list[str]]:
    p = Paper(width=900, bg=(253, 252, 249), margin=48)
    _emblem(p, doc["initials"], rng)
    p.line(doc["vendor_print"], "serif_bold", 34, "c")
    if doc.get("unit_of"):
        p.line(f"(A unit of {doc['unit_of']})", "serif", 16, "c")
    for a in doc["address"]:
        p.line(a, "serif", 18, "c")
    if doc.get("gstin_print"):
        p.line(f"GSTIN: {doc['gstin_print']}", "sans", 17, "c")
    p.gap(6)
    p.line("GUEST FOLIO / TAX INVOICE", "sans_bold", 22, "c")
    p.rule(dashed=False)
    p.lr(f"Folio No: {doc['invoice_number']}", f"Bill Date: {doc['date_print']}", "sans", 18)
    p.lr(f"Guest: {doc['guest']}", f"Room: {doc['room']} ({doc['room_type']})", "sans", 18)
    p.lr(f"Arrival: {doc['arrival_print']}", f"Departure: {doc['date_print']}", "sans", 18)
    p.lr(f"Company: {doc['company']}", f"Nights: {doc['nights']}  Pax: 1", "sans", 18)
    p.rule(dashed=False)
    p.cols(
        [
            ("Date", 0.055, "l"),
            ("Particulars", 0.22, "l"),
            ("CGST", 0.66, "r"),
            ("SGST", 0.79, "r"),
            ("Amount", 0.945, "r"),
        ],
        "sans_bold",
        17,
    )
    p.rule(dashed=False)
    for night in doc["nights_list"]:
        p.cols(
            [
                (night["date"].strftime("%d/%m/%y"), 0.055, "l"),
                (f"Room Tariff - {doc['room_type']}", 0.22, "l"),
                (inr(night["cgst"]), 0.66, "r"),
                (inr(night["cgst"]), 0.79, "r"),
                (inr(night["tariff"]), 0.945, "r"),
            ],
            "sans",
            17,
        )
    for extra in doc.get("extras", []):
        p.cols(
            [
                (extra["date"].strftime("%d/%m/%y"), 0.055, "l"),
                (extra["description"], 0.22, "l"),
                (inr(extra["cgst"]), 0.66, "r"),
                (inr(extra["cgst"]), 0.79, "r"),
                (inr(extra["amount"]), 0.945, "r"),
            ],
            "sans",
            17,
        )
    p.rule(dashed=False)
    p.lr("Taxable Value", inr(doc["subtotal"]), "sans", 19)
    p.lr(f"CGST @ {doc['gst_rate'] / 2:g}%", inr(doc["tax_amount"] / 2), "sans", 19)
    p.lr(f"SGST @ {doc['gst_rate'] / 2:g}%", inr(doc["tax_amount"] / 2), "sans", 19)
    p.lr("TOTAL (INR)", inr(doc["total_amount"]), "sans_bold", 24)
    p.lr("Less: Settlement", f"({inr(doc['total_amount'])})", "sans", 18)
    p.lr("Balance", "0.00", "sans", 18)
    p.rule(dashed=False)
    p.line(f"Settlement: {doc['payment_print']}", "sans", 18)
    p.gap(18)
    p.lr("Guest Signature ____________", "Cashier ____________", "sans", 16)
    p.line("Check-out time 12 noon. Thank you for staying with us.", "serif", 15, "c")
    return p.render(), p.text


def stationery(doc: Doc, rng: random.Random) -> tuple[Image.Image, list[str]]:
    p = Paper(width=860, bg=(255, 255, 253), margin=40)
    top = p.y
    p.line(doc["vendor_print"], "sans_bold", 32, "l")
    for a in doc["address"]:
        p.line(a, "sans", 17)
    p.line(
        f"GSTIN: {doc['gstin_print']}" if doc.get("gstin_print") else "GSTIN: Applied for", "sans_bold", 17
    )
    p.ops.append(("text", ("TAX INVOICE", "sans_bold", 26, "r", top, INK)))
    p.text.append("TAX INVOICE")
    p.ops.append(("text", (f"Invoice No: {doc['invoice_number']}", "sans", 17, "r", top + 40, INK)))
    p.ops.append(("text", (f"Date: {doc['date_print']}", "sans", 17, "r", top + 64, INK)))
    p.text += [f"Invoice No: {doc['invoice_number']}", f"Date: {doc['date_print']}"]
    p.gap(6)
    p.line(f"Bill to: {doc['buyer']}", "sans", 17)
    p.line(f"Place of supply: {doc['state']}", "sans", 17)
    p.gap(4)
    y0 = p.y
    p.cols(
        [
            ("#", 0.06, "l"),
            ("Description", 0.1, "l"),
            ("HSN", 0.55, "l"),
            ("Qty", 0.69, "r"),
            ("Rate", 0.81, "r"),
            ("Amount", 0.95, "r"),
        ],
        "sans_bold",
        17,
    )
    for i, it in enumerate(doc["items"], 1):
        p.cols(
            [
                (str(i), 0.06, "l"),
                (it["description"], 0.1, "l"),
                (it["hsn"], 0.55, "l"),
                (str(int(it["quantity"])), 0.69, "r"),
                (inr(it["unit_price"]), 0.81, "r"),
                (inr(it["amount"]), 0.95, "r"),
            ],
            "sans",
            17,
        )
    p.box(0.045 * p.width, y0 - 6, 0.96 * p.width, p.y + 4, outline=(80, 80, 80))
    p.gap(14)
    p.lr("", f"Taxable Value   {inr(doc['subtotal'])}", "sans", 18)
    p.lr("", f"CGST @ {doc['gst_rate'] / 2:g}%   {inr(doc['tax_amount'] / 2)}", "sans", 18)
    p.lr("", f"SGST @ {doc['gst_rate'] / 2:g}%   {inr(doc['tax_amount'] / 2)}", "sans", 18)
    p.lr("", f"Invoice Total (Rs.)   {inr(doc['total_amount'])}", "sans_bold", 22)
    p.line(f"Amount in words: {doc['amount_words']}", "sans", 16)
    p.line(f"Payment received: {doc['payment_print']}", "sans", 17)
    p.gap(18)
    p.lr("E. & O.E.", f"For {doc['vendor_print'].title()}", "sans", 16)
    p.gap(24)
    p.lr("", "Authorised Signatory", "sans", 15)
    return p.render(), p.text


def upi(doc: Doc, rng: random.Random) -> tuple[Image.Image, list[str]]:
    w = 720
    p = Paper(width=w, bg=(255, 255, 255), margin=48)
    blue = (23, 63, 140)
    p.ops.append(("box", (0, 0, w, 64, (245, 246, 248), (245, 246, 248), 0)))
    p.ops.append(("text", (doc["status_time"], "sans_bold", 22, "l", 18, INK)))
    p.ops.append(("text", (f"{rng.randint(28, 96)}%", "sans", 20, "r", 20, INK)))
    p.y = 96
    p.line("PayNow", "sans_bold", 30, "c", ink=blue)
    p.gap(40)
    cy = p.y + 70
    p.ops.append(("check", (w // 2, cy, 70, (22, 150, 90))))
    p.y = cy + 100
    p.line("Payment Successful", "sans_bold", 32, "c")
    p.gap(6)
    p.line(f"₹{inr(doc['total_amount'], 0 if doc['total_amount'].is_integer() else 2)}", "unicode", 58, "c")
    p.line(doc["datetime_print"], "sans", 20, "c", ink=(100, 100, 100))
    p.gap(30)
    p.rule(dashed=False)
    p.line("Paid to", "sans", 18, ink=(110, 110, 110))
    p.line(doc["payee_print"], "sans_bold", 24)
    p.line(doc["payee_vpa"], "sans", 19, ink=(80, 80, 80))
    p.gap(8)
    p.line("From", "sans", 18, ink=(110, 110, 110))
    p.line(doc["payer"], "sans_bold", 22)
    p.rule(dashed=False)
    p.lr("UPI Transaction ID", doc["upi_txn_id"], "sans", 20)
    p.lr("PayNow Txn ID", doc["app_txn_id"], "sans", 20)
    if doc.get("note"):
        p.lr("Note", doc["note"], "sans", 20)
    p.rule(dashed=False)
    p.gap(30)
    pill = p.y
    p.box(48, pill, w // 2 - 12, pill + 64, outline=blue, radius=32)
    p.box(w // 2 + 12, pill, w - 48, pill + 64, outline=blue, radius=32)
    p.ops.append(("cols", ([("Share", 0.215, "l"), ("Done", 0.70, "l")], "sans_bold", 22, pill + 18, blue)))
    p.y += 100
    p.line("Powered by UPI", "sans", 17, "c", ink=(120, 120, 120))
    img = p.render(p.y + 120)
    return img, p.text


def handwritten(doc: Doc, rng: random.Random) -> tuple[Image.Image, list[str]]:
    """Printed cash-memo pad filled in by hand (jittered handwriting font)."""
    w = 620
    pad = (247, 243, 226)
    red = (170, 40, 40)
    p = Paper(width=w, bg=pad, margin=30)
    p.line(doc["vendor_print"], "serif_bold", 30, "c", ink=red)
    for a in doc["address"]:
        p.line(a, "serif", 16, "c", ink=red)
    p.line("CASH MEMO", "sans_bold", 20, "c", ink=red)
    p.rule(dashed=False)
    header_y = p.y
    p.ops.append(("text", (f"No. {doc['invoice_number']}", "sans_bold", 19, "l", header_y, red)))
    p.ops.append(
        ("cols", ([("Date", 0.64, "l"), ("____________", 0.95, "r")], "sans_bold", 19, header_y, red))
    )
    p.text.append(f"No. {doc['invoice_number']}")
    p.y += 40
    p.ops.append(("text", ("M/s ______________________________", "sans", 18, "l", p.y, red)))
    p.y += 40
    p.cols([("Particulars", 0.05, "l"), ("Qty", 0.62, "r"), ("Rs.", 0.92, "r")], "sans_bold", 18, ink=red)
    p.rule(dashed=False)
    body_y = p.y
    p.y += 44 * max(len(doc["items"]), 4) + 10
    p.rule(dashed=False)
    total_y = p.y
    p.ops.append(("text", ("Total Rs.", "sans_bold", 20, "l", total_y, red)))
    p.y += 50
    p.ops.append(("text", ("Signature ________", "sans", 17, "r", p.y, red)))
    p.y += 30
    img = p.render()
    d = ImageDraw.Draw(img)
    pen = (25, 40, 110)

    def scrawl(x: float, y: float, s: str, size: int = 28) -> None:
        f = font("hand", size)
        for ch in s:
            d.text((x, y + rng.uniform(-2.5, 2.5)), ch, fill=pen, font=f)
            x += d.textlength(ch, font=f) * rng.uniform(0.92, 1.08)

    hand = []
    if doc.get("date_hand"):
        scrawl(w * 0.75, header_y - 12, doc["date_hand"])
        hand.append(f"Date {doc['date_hand']}")
    if doc.get("customer"):
        scrawl(80, header_y + 26, doc["customer"])
        hand.append(f"M/s {doc['customer']}")
    for i, it in enumerate(doc["items"]):
        y = body_y + 44 * i
        scrawl(36, y, it["description"])
        scrawl(w * 0.58, y, str(int(it["quantity"])))
        scrawl(w * 0.80, y, f"{it['amount']:.0f}/-")
        hand.append(f"{it['description']}  {int(it['quantity'])}  {it['amount']:.0f}/-")
    scrawl(w * 0.76, total_y - 8, f"{doc['total_amount']:.0f}/-", 32)
    hand.append(f"Total Rs. {doc['total_amount']:.0f}/-")
    if doc.get("payment_hand"):
        scrawl(36, total_y + 40, doc["payment_hand"], 24)
        hand.append(doc["payment_hand"])
    if doc.get("smudge_date"):
        box = (int(w * 0.73), header_y - 18, w - 30, header_y + 30)
        region = img.crop(box).filter(ImageFilter.GaussianBlur(6))
        overlay = Image.new("RGB", region.size, (150, 140, 120))
        img.paste(Image.blend(region, overlay, 0.35), box)
    return img, p.text[:4] + hand + p.text[4:]


TEMPLATES = {
    "restaurant": restaurant,
    "ride": ride,
    "fuel": fuel,
    "hotel": hotel,
    "stationery": stationery,
    "upi": upi,
    "handwritten": handwritten,
}
