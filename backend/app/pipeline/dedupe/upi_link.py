"""UPI screenshot <-> invoice linking: the screenshot is proof of payment, not a second expense."""

from app.domain.enums import DocType
from app.domain.models import LineItem
from app.pipeline.dedupe.fuzzy import norm_invoice, vendor_similarity

PAYEE_MIN = 0.70
AMOUNT_TOL_INR = 1.0
MAX_DAY_GAP = 1


def is_upi_screenshot(line: LineItem) -> bool:
    return line.extracted.doc_type.value == DocType.UPI_SCREENSHOT


def upi_link_evidence(upi: LineItem, invoice: LineItem) -> dict | None:
    """Evidence dict if `upi` (a screenshot) pays for `invoice`, else None."""
    if not is_upi_screenshot(upi) or is_upi_screenshot(invoice):
        return None
    if abs(upi.amount_inr - invoice.amount_inr) > AMOUNT_TOL_INR:
        return None
    du, di = upi.extracted.date.value, invoice.extracted.date.value
    if du is None or di is None or abs((du - di).days) > MAX_DAY_GAP:
        return None
    payee = upi.extracted.payee_name.value or upi.extracted.vendor_name.value
    payee_sim = vendor_similarity(payee, invoice.extracted.vendor_name.value)
    txn = norm_invoice(upi.extracted.upi_txn_id.value)
    txn_in_invoice = bool(txn) and txn in norm_invoice(invoice.extracted.raw_text)
    if payee_sim < PAYEE_MIN and not txn_in_invoice:
        return None
    return {"layer": "upi_link", "payee_similarity": round(payee_sim, 3), "txn_id_in_invoice": txn_in_invoice}
