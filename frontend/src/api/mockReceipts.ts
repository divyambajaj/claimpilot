import type {
  Category,
  DemoReceipt,
  DocType,
  ExtractedField,
  ExtractedReceipt,
  Finding,
  FieldOrigin,
  PaymentMethod,
  QuestionKind,
  ReceiptItem,
  ReceiptQuality,
} from "../types";

/** All vendors, GSTINs, people and UPI handles below are synthetic. */

export function fld<T>(
  value: T | null,
  confidence: number,
  source_snippet: string | null = null,
  origin: FieldOrigin = "llm",
): ExtractedField<T> {
  return { value, confidence, source_snippet, origin, history: [] };
}

interface ReceiptSpec {
  doc_type: [DocType, number];
  vendor_name: [string | null, number, string?];
  vendor_gstin?: [string | null, number, string?, FieldOrigin?];
  invoice_number?: [string | null, number, string?];
  date: [string | null, number, string?];
  subtotal?: [number | null, number, string?];
  tax_amount?: [number | null, number, string?];
  total_amount: [number | null, number, string?];
  payment_method: [PaymentMethod, number, string?, FieldOrigin?];
  upi_txn_id?: [string | null, number, string?];
  payee_name?: [string | null, number, string?];
  city?: [string | null, number, string?, FieldOrigin?];
  category: [Category, number, string?];
  attendees_count?: [number | null, number, string?, FieldOrigin?];
  items?: ReceiptItem[];
  raw_text: string;
  quality: ReceiptQuality;
}

function receipt(s: ReceiptSpec): ExtractedReceipt {
  const t = <T>(x: [T | null, number, string?, FieldOrigin?] | undefined): ExtractedField<T> =>
    x ? fld<T>(x[0], x[1], x[2] ?? null, x[3] ?? "llm") : fld<T>(null, 0.0, null, "llm");
  return {
    doc_type: fld(s.doc_type[0], s.doc_type[1]),
    vendor_name: t(s.vendor_name),
    vendor_gstin: t(s.vendor_gstin),
    invoice_number: t(s.invoice_number),
    date: t(s.date),
    currency: fld("INR", 0.99, "₹", "validator"),
    subtotal: t(s.subtotal),
    tax_amount: t(s.tax_amount),
    total_amount: t(s.total_amount),
    payment_method: t(s.payment_method),
    upi_txn_id: t(s.upi_txn_id),
    payee_name: t(s.payee_name),
    city: t(s.city),
    category: t(s.category),
    attendees_count: t(s.attendees_count),
    items: s.items ?? [],
    raw_text: s.raw_text,
    quality: s.quality,
  };
}

export interface MockQuestionSpec {
  key: string;
  field: string;
  kind: QuestionKind;
  prompt: string;
  reason: string;
  voi: number;
  choices?: string[];
}

export interface MockTemplate {
  demo: DemoReceipt;
  extracted: ExtractedReceipt;
  category: Category;
  amount: number;
  /** Reimbursable before any answers. */
  reimbursable: number;
  /** Findings present right after processing. */
  findings: Omit<Finding, "id">[];
  questions: MockQuestionSpec[];
  /** "complete" | "excluded" once the user has answered everything; mock logic may override. */
  settledStatus: "complete" | "excluded";
  /** Demo role, used by the mock to wire up links/duplicates. */
  role?: { upiFor?: string; duplicateOf?: string };
  /** Mock processing time in ms. */
  readMs: number;
}

export const TEMPLATES: MockTemplate[] = [
  {
    demo: {
      name: "saffron-table-dinner",
      title: "Team dinner, Saffron Table",
      doc_type: "invoice",
      description: "GST invoice, card payment",
      amount_inr: 3860,
    },
    extracted: receipt({
      doc_type: ["invoice", 0.97],
      vendor_name: ["Saffron Table Kitchen", 0.95, "SAFFRON TABLE KITCHEN · Lower Parel"],
      vendor_gstin: ["27AAKCS4821M1ZQ", 0.92, "GSTIN: 27AAKCS4821M1ZQ"],
      invoice_number: ["ST/2026/04418", 0.9, "Bill No: ST/2026/04418"],
      date: ["2026-10-06", 0.93, "Date: 06/10/2026  21:42"],
      subtotal: [3676.19, 0.9, "Sub Total 3,676.19"],
      tax_amount: [183.81, 0.88, "CGST 2.5% 91.90  SGST 2.5% 91.91"],
      total_amount: [3860, 0.96, "GRAND TOTAL ₹ 3,860.00"],
      payment_method: ["card", 0.86, "VISA **** 4417"],
      city: ["Mumbai", 0.9, "Lower Parel, Mumbai 400013"],
      category: ["meals", 0.94],
      attendees_count: [2, 0.46, "Cvr: 2?"],
      items: [
        { description: "Dal makhani", quantity: 2, unit_price: 420, amount: 840 },
        { description: "Paneer tikka", quantity: 1, unit_price: 560, amount: 560 },
        { description: "Butter naan", quantity: 6, unit_price: 95, amount: 570 },
        { description: "Veg biryani", quantity: 2, unit_price: 480, amount: 960 },
        { description: "Fresh lime soda", quantity: 4, unit_price: 186.55, amount: 746.19 },
      ],
      raw_text: "SAFFRON TABLE KITCHEN Lower Parel Mumbai GSTIN 27AAKCS4821M1ZQ Bill No ST/2026/04418 ...",
      quality: "good",
    }),
    category: "meals",
    amount: 3860,
    reimbursable: 1500,
    findings: [
      {
        kind: "policy",
        severity: "warn",
        rule_id: "MEALS_CAP_PER_PERSON",
        message: "Meal works out to ₹1,930/person, above the ₹750 limit; reimbursed at cap.",
        citation: null,
        evidence: { per_person_amount: 1930, cap_inr: 750, attendees_count: 2, attendees_confidence: 0.46 },
        resolution: "open",
      },
    ],
    questions: [
      {
        key: "attendees",
        field: "attendees_count",
        kind: "value",
        prompt: "How many people were at the Saffron Table dinner?",
        reason: "Affects reimbursable amount. The limit is ₹750 per person, and the cover count on the bill is hard to read.",
        voi: 0.81,
      },
    ],
    settledStatus: "complete",
    readMs: 2600,
  },
  {
    demo: {
      name: "rydego-airport",
      title: "Cab to airport, RydeGo",
      doc_type: "ride_receipt",
      description: "Ride receipt, paid by UPI",
      amount_inr: 486,
    },
    extracted: receipt({
      doc_type: ["ride_receipt", 0.98],
      vendor_name: ["RydeGo", 0.98, "RydeGo · Trip receipt"],
      invoice_number: ["RG-7Q2K-91MX", 0.94, "Trip ID RG-7Q2K-91MX"],
      date: ["2026-10-05", 0.97, "5 Oct 2026, 06:12"],
      total_amount: [486, 0.97, "Total fare ₹486.00"],
      tax_amount: [23.14, 0.8, "Includes GST ₹23.14"],
      payment_method: ["upi", 0.93, "Paid via UPI"],
      city: ["Mumbai", 0.92, "Andheri East → T2 Departures"],
      category: ["travel_local", 0.96],
      raw_text: "RydeGo Trip receipt Trip ID RG-7Q2K-91MX 5 Oct 2026 Andheri East to T2 Departures 18.4 km Total fare 486.00",
      quality: "good",
    }),
    category: "travel_local",
    amount: 486,
    reimbursable: 486,
    findings: [],
    questions: [],
    settledStatus: "complete",
    readMs: 1700,
  },
  {
    demo: {
      name: "harbour-view-folio",
      title: "Hotel, Harbour View Residency",
      doc_type: "hotel_folio",
      description: "Hotel folio, 1 night",
      amount_inr: 5782,
    },
    extracted: receipt({
      doc_type: ["hotel_folio", 0.96],
      vendor_name: ["Harbour View Residency", 0.96, "HARBOUR VIEW RESIDENCY"],
      vendor_gstin: ["27AABFH7310Q1Z2", 0.94, "GSTIN 27AABFH7310Q1Z2"],
      invoice_number: ["HVR-F-22871", 0.92, "Folio No. HVR-F-22871"],
      date: ["2026-10-05", 0.9, "Departure 06-Oct-26 · Arrival 05-Oct-26"],
      subtotal: [5162.5, 0.9, "Room charges 5,162.50"],
      tax_amount: [619.5, 0.9, "GST @12% 619.50"],
      total_amount: [5782, 0.97, "Balance settled ₹5,782.00"],
      payment_method: ["card", 0.9, "Settled: MASTERCARD"],
      city: ["Mumbai", 0.95, "Colaba, Mumbai"],
      category: ["lodging", 0.98],
      raw_text: "HARBOUR VIEW RESIDENCY Colaba Mumbai Folio HVR-F-22871 Room 512 Deluxe 1 night 5162.50 GST 619.50 total 5782.00",
      quality: "good",
    }),
    category: "lodging",
    amount: 5782,
    reimbursable: 5782,
    findings: [],
    questions: [],
    settledStatus: "complete",
    readMs: 2900,
  },
  {
    demo: {
      name: "paperleaf-invoice",
      title: "Workshop supplies, Paperleaf",
      doc_type: "invoice",
      description: "GST invoice, paid by UPI",
      amount_inr: 6450,
    },
    extracted: receipt({
      doc_type: ["invoice", 0.97],
      vendor_name: ["Paperleaf Stationers Pvt Ltd", 0.95, "PAPERLEAF STATIONERS PVT LTD"],
      vendor_gstin: ["27AAGCP5519L1ZK", 0.96, "GSTIN/UIN: 27AAGCP5519L1ZK"],
      invoice_number: ["PL/26-27/1182", 0.93, "Invoice No. PL/26-27/1182"],
      date: ["2026-10-07", 0.95, "Dated 07-10-2026"],
      subtotal: [5466.1, 0.92, "Taxable value 5,466.10"],
      tax_amount: [983.9, 0.91, "IGST 18% 983.90"],
      total_amount: [6450, 0.98, "Total ₹6,450.00"],
      payment_method: ["upi", 0.84, "Mode: UPI"],
      city: ["Mumbai", 0.88, "Fort, Mumbai 400001"],
      category: ["office", 0.9],
      items: [
        { description: "Flip chart pads (pack of 4)", quantity: 3, unit_price: 780, amount: 2340 },
        { description: "Whiteboard markers, assorted", quantity: 10, unit_price: 112.61, amount: 1126.1 },
        { description: "A4 notebooks, ruled", quantity: 40, unit_price: 50, amount: 2000 },
      ],
      raw_text: "PAPERLEAF STATIONERS PVT LTD Fort Mumbai GSTIN 27AAGCP5519L1ZK Invoice PL/26-27/1182 Total 6450.00 Mode UPI",
      quality: "good",
    }),
    category: "office",
    amount: 6450,
    reimbursable: 6450,
    findings: [],
    questions: [],
    settledStatus: "complete",
    readMs: 2400,
  },
  {
    demo: {
      name: "paynow-6450",
      title: "UPI payment, ₹6,450",
      doc_type: "upi_screenshot",
      description: "PayNow screenshot",
      amount_inr: 6450,
    },
    extracted: receipt({
      doc_type: ["upi_screenshot", 0.99],
      vendor_name: ["Paperleaf Stationers", 0.82, "Paid to PAPERLEAF STATIONERS"],
      date: ["2026-10-07", 0.96, "07 Oct 2026, 4:18 pm"],
      total_amount: [6450, 0.99, "₹6,450"],
      payment_method: ["upi", 0.99, "PayNow UPI"],
      upi_txn_id: ["428913765012", 0.97, "UPI Ref No. 428913765012"],
      payee_name: ["PAPERLEAF STATIONERS", 0.9, "paperleaf.stn@okbank"],
      category: ["office", 0.62, undefined],
      raw_text: "PayNow Payment successful 6450 Paid to PAPERLEAF STATIONERS paperleaf.stn@okbank UPI Ref No 428913765012",
      quality: "good",
    }),
    category: "office",
    amount: 6450,
    reimbursable: 0,
    findings: [],
    questions: [],
    settledStatus: "excluded",
    role: { upiFor: "paperleaf-invoice" },
    readMs: 1400,
  },
  {
    demo: {
      name: "highway-fuels-handwritten",
      title: "Fuel, Shree Highway Fuels",
      doc_type: "handwritten",
      description: "Handwritten bill, cash",
      amount_inr: 2100,
    },
    extracted: receipt({
      doc_type: ["handwritten", 0.9],
      vendor_name: ["Shree Highway Fuels", 0.78, "Shree Highway Fuels (stamp)"],
      date: [null, 0.0, "Date: __/10/26 (smudged)"],
      total_amount: [2100, 0.83, "Rs 2100/-"],
      payment_method: ["cash", 0.71, "Cash"],
      city: ["Lonavala", 0.58, "NH48, Lonavala", "assumed"],
      category: ["fuel", 0.95],
      items: [{ description: "Petrol 20.4 L @ 102.94", quantity: 20.4, unit_price: 102.94, amount: 2100 }],
      raw_text: "Shree Highway Fuels NH48 Lonavala Petrol 20.4 L Rs 2100 cash",
      quality: "handwritten",
    }),
    category: "fuel",
    amount: 2100,
    reimbursable: 2100,
    findings: [
      {
        kind: "missing",
        severity: "info",
        rule_id: "FUEL_BILL_DATE",
        message: "The date on this fuel bill could not be read.",
        citation: null,
        evidence: { field: "date" },
        resolution: "open",
      },
    ],
    questions: [
      {
        key: "fuel-date",
        field: "date",
        kind: "value",
        prompt: "What date is on the Shree Highway Fuels bill?",
        reason: "Required by policy 6.2. The day is smudged on the handwritten bill.",
        voi: 1.0,
      },
    ],
    settledStatus: "complete",
    readMs: 3300,
  },
  {
    demo: {
      name: "rydego-airport-photo",
      title: "Cab to airport (photo)",
      doc_type: "ride_receipt",
      description: "Photo of a printed receipt",
      amount_inr: 486,
    },
    extracted: receipt({
      doc_type: ["ride_receipt", 0.93],
      vendor_name: ["RydeGo", 0.9, "RydeGo"],
      invoice_number: [null, 0.0],
      date: ["2026-10-05", 0.88, "05 Oct 2026"],
      total_amount: [486, 0.91, "Total ₹486"],
      payment_method: ["upi", 0.8, "UPI"],
      city: ["Mumbai", 0.84, "T2 Departures"],
      category: ["travel_local", 0.94],
      raw_text: "RydeGo receipt 05 Oct 2026 Andheri East T2 Departures Total 486 UPI",
      quality: "blurry",
    }),
    category: "travel_local",
    amount: 486,
    reimbursable: 486,
    findings: [],
    questions: [],
    settledStatus: "complete",
    role: { duplicateOf: "rydego-airport" },
    readMs: 2000,
  },
  {
    demo: {
      name: "rydego-office",
      title: "Cab to client office, RydeGo",
      doc_type: "ride_receipt",
      description: "Ride receipt, same day",
      amount_inr: 312,
    },
    extracted: receipt({
      doc_type: ["ride_receipt", 0.98],
      vendor_name: ["RydeGo", 0.98, "RydeGo · Trip receipt"],
      invoice_number: ["RG-8D4P-22KC", 0.95, "Trip ID RG-8D4P-22KC"],
      date: ["2026-10-05", 0.97, "5 Oct 2026, 10:47"],
      total_amount: [312, 0.97, "Total fare ₹312.00"],
      payment_method: ["upi", 0.92, "Paid via UPI"],
      city: ["Mumbai", 0.93, "BKC → Nariman Point"],
      category: ["travel_local", 0.96],
      raw_text: "RydeGo Trip receipt Trip ID RG-8D4P-22KC 5 Oct 2026 BKC to Nariman Point 14.1 km Total fare 312.00",
      quality: "good",
    }),
    category: "travel_local",
    amount: 312,
    reimbursable: 312,
    findings: [],
    questions: [],
    settledStatus: "complete",
    readMs: 1600,
  },
  {
    demo: {
      name: "bloom-cafe-lunch",
      title: "Client lunch, Bloom Café",
      doc_type: "receipt",
      description: "Receipt from late August",
      amount_inr: 1240,
    },
    extracted: receipt({
      doc_type: ["receipt", 0.95],
      vendor_name: ["Bloom Café", 0.93, "BLOOM CAFÉ · Indiranagar"],
      vendor_gstin: ["29AAHFB2207N1ZC", 0.9, "GSTIN 29AAHFB2207N1ZC"],
      invoice_number: ["BC-55120", 0.9, "Inv BC-55120"],
      date: ["2026-08-28", 0.95, "28/08/2026 13:20"],
      total_amount: [1240, 0.96, "Total 1,240.00"],
      payment_method: ["card", 0.88, "Card"],
      city: ["Bengaluru", 0.94, "Indiranagar, Bengaluru"],
      category: ["meals", 0.95],
      attendees_count: [2, 0.91, "Guests: 2"],
      raw_text: "BLOOM CAFE Indiranagar Bengaluru 28/08/2026 Guests 2 Total 1240.00",
      quality: "good",
    }),
    category: "meals",
    amount: 1240,
    reimbursable: 1240,
    findings: [
      {
        kind: "policy",
        severity: "warn",
        rule_id: "SUBMISSION_WINDOW_30D",
        message: "Expense is 43 days old; policy window is 30 days. Add a justification.",
        citation: null,
        evidence: { days_since_expense: 43 },
        resolution: "open",
      },
    ],
    questions: [
      {
        key: "late-justify",
        field: "justification",
        kind: "justify_flag",
        prompt: "The Bloom Café lunch is 43 days old. Why is it being claimed late?",
        reason: "Needed to keep this line in the claim. Finance reviews late claims.",
        voi: 0.6,
      },
    ],
    settledStatus: "complete",
    readMs: 1900,
  },
];
