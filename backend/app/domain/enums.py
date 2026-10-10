"""Domain enumerations (string-valued so they serialise as plain JSON)."""

from enum import StrEnum


class DocType(StrEnum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    UPI_SCREENSHOT = "upi_screenshot"
    HOTEL_FOLIO = "hotel_folio"
    RIDE_RECEIPT = "ride_receipt"
    FUEL = "fuel"
    HANDWRITTEN = "handwritten"
    UNKNOWN = "unknown"


class Category(StrEnum):
    MEALS = "meals"
    TRAVEL_LOCAL = "travel_local"
    TRAVEL_INTERCITY = "travel_intercity"
    LODGING = "lodging"
    FUEL = "fuel"
    OFFICE = "office"
    INTERNET_PHONE = "internet_phone"
    PERSONAL = "personal"  # grooming, personal shopping, entertainment: never reimbursable (policy 6.3)
    OTHER = "other"


class LineStatus(StrEnum):
    PROCESSING = "processing"
    MISSING_INFO = "missing_info"
    FLAGGED = "flagged"
    COMPLETE = "complete"
    EXCLUDED = "excluded"
    ERROR = "error"


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class FindingKind(StrEnum):
    POLICY = "policy"
    DUPLICATE = "duplicate"
    VALIDATION = "validation"
    MISSING = "missing"


class PaymentMethod(StrEnum):
    UPI = "upi"
    CARD = "card"
    CASH = "cash"
    UNKNOWN = "unknown"


class PayeeType(StrEnum):
    MERCHANT = "merchant"
    INDIVIDUAL = "individual"
    UNKNOWN = "unknown"
