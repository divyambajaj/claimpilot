import type { Category, DocType, LineStatus, PayeeType, PaymentMethod } from "../types";

const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** ₹1,23,456.00 (Indian digit grouping). */
export function formatINR(n: number | null | undefined, opts: { decimals?: boolean } = {}): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const decimals = opts.decimals ?? true;
  const sign = n < 0 ? "−" : "";
  return `${sign}₹${(decimals ? inr2 : inr0).format(Math.abs(n))}`;
}

export function formatNumber(n: number, digits = 0): string {
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

export function formatPct(r: number, digits = 0): string {
  return `${(r * 100).toFixed(digits)}%`;
}

export function formatMs(ms: number): string {
  if (ms < 10) return `${Number(ms.toFixed(1))} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-03" -> "3 Oct 2026" (no timezone shift for plain dates). */
export function formatDate(iso: string | null | undefined, opts: { year?: boolean } = {}): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const [, y, mo, d] = m;
  const s = `${Number(d)} ${MONTHS[Number(mo) - 1]}`;
  return opts.year === false ? s : `${s} ${y}`;
}

export function formatDateTime(iso: string): string {
  const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`); // the API sends naive UTC timestamps
  if (Number.isNaN(d.getTime())) return iso;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hh}:${mm}`;
}

export const CATEGORY_LABEL: Record<Category, string> = {
  meals: "Meals",
  travel_local: "Local travel",
  travel_intercity: "Intercity travel",
  lodging: "Lodging",
  fuel: "Fuel",
  office: "Office supplies",
  internet_phone: "Internet & phone",
  personal: "Personal",
  other: "Other",
};

export const PAYEE_TYPE_LABEL: Record<PayeeType, string> = {
  merchant: "Business",
  individual: "Person",
  unknown: "Unknown",
};

export const DOC_TYPE_LABEL: Record<DocType, string> = {
  invoice: "GST invoice",
  receipt: "Receipt",
  upi_screenshot: "UPI screenshot",
  hotel_folio: "Hotel folio",
  ride_receipt: "Ride receipt",
  fuel: "Fuel slip",
  handwritten: "Handwritten bill",
  unknown: "Document",
};

export const PAYMENT_LABEL: Record<PaymentMethod, string> = {
  upi: "UPI",
  card: "Card",
  cash: "Cash",
  unknown: "Unknown",
};

export const STATUS_LABEL: Record<LineStatus, string> = {
  processing: "Reading",
  missing_info: "Needs info",
  flagged: "Flagged",
  complete: "Complete",
  excluded: "Excluded",
  error: "Error",
};

export const FIELD_LABEL: Record<string, string> = {
  doc_type: "Document type",
  vendor_name: "Vendor",
  vendor_gstin: "GSTIN",
  invoice_number: "Invoice no.",
  date: "Date",
  currency: "Currency",
  subtotal: "Subtotal",
  tax_amount: "Tax",
  total_amount: "Total",
  payment_method: "Paid by",
  upi_txn_id: "UPI ref",
  payee_name: "Payee",
  city: "City",
  category: "Category",
  attendees_count: "Attendees",
};

export function fieldLabel(f: string): string {
  return FIELD_LABEL[f] ?? f.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function pluralize(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
