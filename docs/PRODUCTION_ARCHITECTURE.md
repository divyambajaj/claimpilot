# ClaimPilot — Production Architecture

How the prototype in this repository becomes a production service for thousands of employees. The core design does not change: **the AI only reads documents; deterministic company rules make every decision.** What changes is everything around it: identity, scale, storage, security, integrations and operations.

---

## 1. System overview

```mermaid
flowchart TB
  subgraph Channels["1 · Employee channels"]
    direction LR
    WEB["Web app"] ~~~ MOB["Mobile app<br/>(camera capture)"] ~~~ CHAT["Chat channels<br/>(Teams / WhatsApp / email-in)"]
  end

  subgraph Edge["2 · Edge & identity"]
    direction LR
    WAF["WAF + CDN"] --> GW["API Gateway<br/>auth, rate limits, tracing IDs"] <--> SSO["Corporate SSO<br/>(OIDC / SAML)"]
  end

  subgraph Core["3 · ClaimPilot services (Kubernetes)"]
    direction LR
    API["Claim API<br/>REST + live updates"] --> ORCH["Claim Orchestrator<br/>state machine"]
    ORCH --> RULES["Rules Engine<br/>versioned policy"]
    ORCH --> DUP["Duplicate & Fraud<br/>checks"]
    ORCH --> QP["Question Planner<br/>+ answer checks"]
    ADMIN["Admin & Finance<br/>console API"]
    PCOMP["Policy Compiler<br/>policy text → rules"] -.-> RULES
  end

  subgraph AIL["4 · Bill reading (async)"]
    direction LR
    Q[["Queue<br/>(Kafka)"]] --> W["Extraction workers<br/>autoscaled"] --> PII["PII masking"] --> LLMGW["LLM Gateway<br/>routing, fallbacks,<br/>budgets, prompt versions"]
    LLMGW --> PRIV["Private model<br/>(company network)"]
    LLMGW --> CLOUD["Managed model APIs<br/>(any provider)"]
  end

  subgraph Data["5 · Data"]
    direction LR
    PG[("PostgreSQL<br/>claims, tickets")] ~~~ OBJ[("Object storage<br/>bill images, encrypted")] ~~~ REDIS[("Redis<br/>cache")] ~~~ AUD[("Audit log<br/>append-only")]
  end

  subgraph Ent["6 · Enterprise systems"]
    direction LR
    ERP["Finance ERP<br/>(e.g. SAP)"] ~~~ HRMS["HRMS<br/>grade, city, manager"] ~~~ GST["GSTIN<br/>verification"] ~~~ ITSM["Ticketing<br/>(ServiceNow / Jira)"]
  end

  subgraph Obs["Observability & quality"]
    direction LR
    OTEL["OpenTelemetry<br/>traces · metrics · logs"] ~~~ EVAL["Evaluation gate<br/>in CI/CD"]
  end

  Channels --> Edge --> Core
  Core -- "one job per bill" --> AIL
  AIL -- "fields + confidence + source text" --> Core
  Core --> Data
  Core --> Ent
  Core -.-> Obs
  AIL -.-> Obs
```

**In one line per layer:**
- **Channels:** employees submit bills from the web, the mobile camera, or a chat they already use.
- **Edge:** every request is authenticated through corporate SSO, rate-limited and traced from the first hop.
- **Core services:** the same modules as the prototype, split into independently scalable services.
- **AI layer:** a single gateway in front of all models, so the company can switch or mix providers without touching the app, and keep sensitive bills on a private model.
- **Async processing:** bill reading is queued, so a month-end spike never slows the app down.
- **Data:** claims in PostgreSQL, bill images in encrypted object storage, and an append-only audit trail.
- **Enterprise systems:** real ERP, HRMS, GST verification and ticketing replace today's mocks behind the same interfaces.

---

## 2. A claim, end to end

```mermaid
sequenceDiagram
  autonumber
  participant E as Employee
  participant API as Claim API
  participant S3 as Object storage
  participant Q as Queue
  participant W as Extraction worker
  participant G as LLM Gateway
  participant R as Rules + Duplicates
  participant H as HRMS / GST
  participant F as Finance ERP

  E->>API: Upload bills (SSO token)
  API->>S3: Store originals (encrypted, virus-scanned)
  API->>Q: One job per document
  API-->>E: Live progress (SSE)
  Q->>W: Job
  W->>W: Mask phone numbers, UPI IDs, card digits
  W->>G: Read bill (prompt v3, structured output)
  G-->>W: Fields + confidence + source text
  W->>R: Validate, de-duplicate, apply policy
  R->>H: Employee grade & city, GSTIN check
  R-->>API: Findings + only the questions that matter
  API-->>E: Questions (answers checked by rules)
  E->>API: Answers / "raise a ticket"
  API->>F: Submit ready claim (idempotent)
  F-->>API: Reference, then approval
  API-->>E: Status updates
```

---

## 3. Deployment view

```mermaid
flowchart TB
  subgraph Region["Primary region"]
    subgraph K8S["Kubernetes cluster"]
      subgraph NSAPP["claimpilot namespace"]
        A1["Claim API ×3"]
        O1["Orchestrator ×3"]
        W1["Extraction workers<br/>autoscale on queue depth"]
        R1["Rules / Duplicates ×2"]
        G1["LLM Gateway ×2"]
      end
      subgraph NSOBS["observability namespace"]
        OTEL["OpenTelemetry collector"]
      end
    end
    PGP[("PostgreSQL primary")]
    PGR[("Read replica")]
    OBJP[("Object storage")]
    KAF[["Kafka"]]
    VAULT["Secrets manager"]
    GPU["Private model servers<br/>(GPU pool)"]
  end
  subgraph DR["DR region (warm standby)"]
    PGD[("PostgreSQL replica")]
    OBJD[("Replicated object storage")]
  end
  PGP --> PGR
  PGP -. async replication .-> PGD
  OBJP -. cross-region replication .-> OBJD
  NSAPP --> PGP & OBJP & KAF
  NSAPP --> VAULT
  G1 --> GPU
  NSAPP --> OTEL
```

- **Stateless services, horizontal scale:** every service runs at least two replicas behind the gateway. Extraction workers scale with queue depth, so month-end peaks are absorbed by more workers, not slower responses.
- **Data protection:** PostgreSQL has a primary, a read replica for dashboards, and a warm standby in a second region. Receipt storage is replicated across regions.
- **Secrets:** API keys and database credentials live in a secrets manager, never in images or config files.

---

## 4. Observability and quality loop

```mermaid
flowchart LR
  SVC["All services"] -- traces, metrics, logs --> OTEL["OpenTelemetry collector"]
  OTEL --> TR["Tracing<br/>(per-claim timeline)"]
  OTEL --> MET["Metrics + alerts<br/>(latency, error rate, cost/claim)"]
  OTEL --> LOG["Central logs"]
  TR & MET --> DASH["Finance & Ops dashboards"]
  CORR["Employee corrections<br/>(online labels)"] --> EVAL["Evaluation set<br/>(grows weekly)"]
  EVAL --> CI["CI/CD quality gate<br/>accuracy · duplicates · policy · calibration"]
  CI -->|pass| CANARY["Canary release<br/>5% of traffic"]
  CANARY -->|metrics healthy| PROD["Full rollout"]
  CANARY -->|regression| RB["Automatic rollback"]
```

- **Every claim is traced** step by step (read → check → rules → questions → submit), with the model, prompt version, time and cost recorded on each step.
- **Alerts** fire on error rate, slow extraction, cost per claim above budget, and a falling first-pass-ready rate.
- **Testing never stops:** every correction an employee makes becomes a test case. No new prompt or model ships unless it passes the same quality gate this prototype runs in CI, then a canary on 5% of traffic.

---

## 5. Security and compliance

| Area | Production approach |
|---|---|
| Identity | Corporate SSO (OIDC/SAML); role-based access: employee, manager, finance, admin |
| Data in transit / at rest | TLS everywhere; encrypted database and object storage with managed keys |
| Personal data | PII masked before any AI call and before storage; original images kept only as long as the retention policy allows |
| AI data residency | Sensitive bills can be routed to a private model inside the company network; external models only via the gateway with no-retention settings |
| Prompt injection | Bills are treated as untrusted input; model output is schema-validated data and never executed as an instruction |
| Audit | Append-only audit log of every finding, answer, override, ticket and submission, with who and when |
| Uploads | Size and type checks, virus scan, images re-encoded to strip metadata |
| Secrets | Secrets manager with rotation; no keys in code or images |

---

## 6. From prototype to production

| Prototype (this repo) | Production |
|---|---|
| Single FastAPI process | Separate services on Kubernetes, at least 2 replicas each |
| In-process background tasks | Kafka queue + autoscaled extraction workers |
| SQLite | PostgreSQL (primary, replica, DR standby) |
| Local `data/uploads` | Encrypted object storage with lifecycle rules |
| Provider switch by environment variable | LLM Gateway: routing, fallbacks, budgets, caching, private model option |
| Mock finance and tickets | ERP and ticketing connectors behind the same interfaces |
| Demo employee profile | HRMS integration: grade-based limits, base city, approving manager |
| Local GSTIN checksum | Checksum plus live GSTIN verification |
| Spans stored in SQLite | OpenTelemetry → tracing, metrics and logs stack with alerting |
| `make eval` in CI | Same gate plus a growing set from real corrections, then canary releases |
| Rule-based answer checks | Rules first, with a small model only for borderline answers |

**Rollout plan:**
1. **Pilot:** one department, read-only ERP sync, Finance reviews every claim.
2. **Assisted:** auto-submit claims with no open findings; Finance reviews flags and tickets only.
3. **Scale:** all departments, grade-based policy, mobile and chat channels, private model for sensitive categories.

**Capacity planning (illustrative):** 50,000 employees × 4 claims a month × 8 bills = about 1.6 million bill reads a month, around 37 reads a minute on average. Month-end peaks of 10× are handled by scaling extraction workers on queue depth.
