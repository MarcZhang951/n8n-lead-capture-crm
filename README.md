# Lead Capture + CRM (n8n)

**Speed-to-lead: 5 min → 60 sec.**

An n8n workflow that captures inbound leads, validates and de-duplicates them against HubSpot, scores them with GPT-4o plus rule-based safety floors, and routes each lead to the right follow-up channel (Gmail, Slack, Google Sheets) within a minute of submission.

![Reference](docs/reference.webp)

> **Demo workflow.** Every node that needs an account uses mock credentials and pinned mock data. No real API is called and the workflow is meant to be viewed, not executed.

---

## Purpose

Inbound leads lose value fast: the longer a prospect waits for a reply, the lower the chance of a conversation. Manual triage (checking the form, searching the CRM, judging quality, pinging the right rep) typically takes 5+ minutes per lead. This workflow automates that whole chain so that:

- **Incomplete submissions** are logged and the prospect is asked for the missing details automatically.
- **Duplicate submissions** are logged without spamming sales or the prospect.
- **Every valid lead is scored** consistently by an LLM, with deterministic business rules as a guardrail.
- **The CRM stays clean**: new leads become HubSpot contacts, returning leads update the existing record.
- **Sales reacts instantly**: hot leads get a personalised first-touch email plus a Slack alert with a *Claim* button; warm leads land in a shared queue; cold leads are archived for nurturing.

---

## Architecture

```mermaid
flowchart LR
    subgraph S1[1 · Capture & Normalize]
        A[Form Lead In<br/>Webhook] --> B[Scoring Rules<br/>Set] --> C[Normalize Web<br/>Set]
    end

    subgraph S2[2 · Validate & Dedup]
        C --> D{Validate Lead<br/>Switch}
        D -- Missing Email --> E[Log Incomplete Lead<br/>Google Sheets]
        D -- Missing Name --> F[Ask for Details<br/>Gmail]
        D -- Valid Lead --> G[Search by Email<br/>HubSpot]
        G --> H{Is Duplicate?<br/>IF}
        H -- true --> I[Log Duplicate Lead<br/>Google Sheets]
    end

    subgraph S3[3 · AI + Rules Score]
        H -- false --> J[Score Lead LLM<br/>OpenAI gpt-4o]
        J --> K[Parse Score<br/>Code] --> L[Apply Rules Floor<br/>Code]
    end

    subgraph S4[4 · CRM + Outreach + Notify]
        L --> M{Is New Contact?<br/>IF}
        M -- true --> N[Create Contact<br/>HTTP → HubSpot]
        M -- false --> O{Is Auto Followup?<br/>IF}
        O -- true --> P[Update Contact<br/>HTTP → HubSpot]
        O -- false --> Q[Prepare Update Diff<br/>Code] --> R[Notify Sales of Update<br/>HTTP → Slack]
        N --> T{Tier Router<br/>Switch}
        P --> T
        T -- hot --> U[First-Touch Email<br/>Gmail]
        T -- hot --> V[Notify #leads-hot<br/>HTTP → Slack]
        T -- warm --> W[Notify #leads-queue<br/>Slack]
        T -- cold --> X[Cold Lead<br/>Google Sheets]
    end
```

The workflow is a single linear pipeline with four stages. Each stage narrows the set of leads that continue and hands off a clean, enriched item to the next one:

| Stage | Input | Output | Services |
|---|---|---|---|
| 1. Capture & Normalize | Raw form / ad payload | One unified lead object | Webhook |
| 2. Validate & Dedup | Unified lead | Only complete, non-duplicate leads | HubSpot, Gmail, Google Sheets |
| 3. AI + Rules Score | Valid lead | Lead with `score` (0-100) and `tier` (hot / warm / cold) | OpenAI |
| 4. CRM + Outreach + Notify | Scored lead | CRM record + email + team notification | HubSpot, Gmail, Slack, Google Sheets |

### Design decisions

- **Config at the top.** All thresholds live in one *Scoring Rules* node, so sales ops can tune the model without touching logic.
- **LLM is advisory, rules are the floor.** GPT-4o gives nuance (intent, urgency), but a deterministic floor rule guarantees that an obviously strong lead (corporate email + budget + detailed message) is never scored as cold because of a bad generation.
- **Fail soft.** If the LLM response cannot be parsed, the lead falls back to `warm / 50` so a human still sees it instead of it being dropped.
- **Dedup before scoring.** Duplicates are filtered before the LLM call to save tokens and avoid double notifications.
- **Every exit is logged.** Incomplete, duplicate and cold leads are all written to Google Sheets, so nothing disappears silently.
- **HTTP Request where the native node falls short.** HubSpot contact create/update and Slack Block Kit messages (the *Claim* button) use raw API calls for full control over the payload.

---

## Node reference

### Stage 1 · Capture & Normalize

| Node | n8n node | What it does |
|---|---|---|
| **Form Lead In** | Webhook (`POST /lead-in`) | Entry point. Receives submissions from the website form or Facebook Lead Ads (via a forwarder). Mock payload: *Alex Chen, Acme Corp, $30k budget*. |
| **Scoring Rules (edit here)** | Set | Central configuration: `hotThreshold` (80), `warmThreshold` (50), `corpEmailFloor` (50), `budgetFloor` (10,000), `longMessageChars` (80). Passes the original payload through unchanged. |
| **Normalize (Web)** | Set | Maps different source formats into one lead schema: `name`, `email`, `phone`, `company`, `budget`, `message`, `source`. Trims whitespace, lower-cases email and casts budget to a number. |

### Stage 2 · Validate & Dedup

| Node | n8n node | What it does |
|---|---|---|
| **Validate Lead** | Switch (Rules mode) | Routes by data completeness into three outputs: *Missing Email*, *Missing Name*, *Valid Lead*. |
| **Log Incomplete Lead** | Google Sheets – Append | Writes leads without an email to the `Incomplete` sheet. There is no way to contact them, so they are kept for manual review only. |
| **Ask for Details** | Gmail – Send | Lead has an email but no name: sends a short, friendly reply asking for the missing details. |
| **Search by Email** | HubSpot – Contact Search | Looks up the email in HubSpot to find an existing contact and its history. Mock result: no existing contact. |
| **Is Duplicate?** | IF | Checks whether this is a repeated submission within a short window (e.g. a double-clicked form). |
| **Log Duplicate Lead** | Google Sheets – Append | Duplicates are logged to the `Duplicates` sheet only. No CRM change, no email, no notification. |

### Stage 3 · AI + Rules Score

| Node | n8n node | What it does |
|---|---|---|
| **Score Lead (LLM)** | OpenAI – Message a Model (`gpt-4o`) | Sends the normalized lead to GPT-4o with a qualification prompt. Returns JSON: `score` (0-100), `tier`, `reason`, and a draft first-touch `message`. Mock output: score 86, tier hot. |
| **Parse Score** | Code | Parses the LLM JSON inside a try/catch. On failure it falls back to `score: 50, tier: warm`. Merges the AI fields back onto the lead object. |
| **Apply Rules Floor** | Code | Applies deterministic business rules from *Scoring Rules*: a non-free-mail domain with budget ≥ floor and a detailed message is raised to at least `corpEmailFloor`. Then derives the final `tier` from the thresholds. |

### Stage 4 · CRM + Outreach + Notify

| Node | n8n node | What it does |
|---|---|---|
| **Is New Contact?** | IF | `true` if the HubSpot search returned no contact. |
| **Create Contact** | HTTP Request – `POST /crm/v3/objects/contacts` | Creates the HubSpot contact with name, email, phone, company, lead status `NEW` and `lead_score`. |
| **Is Auto Followup?** | IF | For existing contacts: `true` if the contact is still in lifecycle stage `lead`, meaning automation may continue. `false` means a rep already owns the relationship. |
| **Update Contact** | HTTP Request – `PATCH /crm/v3/objects/contacts/{id}` | Updates `lead_score` and lead status on the existing HubSpot contact, then continues to routing. |
| **Prepare Update Diff** | Code | For contacts owned by a rep: compares submitted fields with the CRM record and builds a human-readable diff (e.g. `phone: old → new`). |
| **Notify Sales of Update** | HTTP Request – Slack `chat.postMessage` | Posts the diff to `#leads-updates` so the owning rep knows the customer came back, without automated outreach interfering. |
| **Tier Router** | Switch (Rules mode) | Routes by final `tier` into *hot*, *warm* and *cold* outputs. |
| **First-Touch Email** | Gmail – Send | Hot leads only: sends the personalised email drafted by GPT-4o immediately. This is the speed-to-lead win. |
| **Notify #leads-hot** | HTTP Request – Slack `chat.postMessage` | Hot leads only: posts an alert with a Block Kit *Claim* button so the first available rep takes ownership. |
| **Notify #leads-queue** | Slack – Send Message | Warm leads: posts to a shared queue channel for follow-up during normal working hours. |
| **Cold Lead** | Google Sheets – Append | Cold leads: archived in the `Cold` sheet for nurture campaigns, with no sales interruption. |

### Sticky notes

Four colour-coded sticky notes on the canvas label the stages: red *Capture & Normalize*, green *Validate & Dedup*, blue *AI + Rules Score*, grey *CRM + Outreach + Notify*. The capture note also lists alternative CRM sync targets (GoHighLevel via `n8n-nodes-base.highLevel`, Close.io via `httpRequest`).

---

## Mock data

| What | How it is mocked |
|---|---|
| Credentials | `mock-credentials.json` defines Gmail, Google Sheets, HubSpot, OpenAI and Slack credentials with fake values (`sk-mock-000000`, `xoxb-mock-000000`, …). They only exist so the nodes show no "credentials missing" warning. |
| Service responses | 13 nodes have **pinned data** (Webhook, 3× Sheets, 2× Gmail, HubSpot, OpenAI, 4× HTTP Request, Slack). Open any node to see a realistic sample output. |
| Spreadsheet / channels | Sheet ID `1MOCK-leads-sheet-id`, channels `#leads-hot`, `#leads-queue`, `#leads-updates`. |

To make it real, replace the mock credentials with real ones, set the real Google Sheet ID, unpin the data and activate the workflow.

---

## Files

| File | Purpose |
|---|---|
| `lead-capture-crm.json` | The n8n workflow, ready to import |
| `mock-credentials.json` | Fake credentials (no real secrets) |
| `build_workflow.py` | Python generator that produces both JSON files |
| `docs/reference.webp` | Reference diagram the workflow was built from |

## Run locally

```bash
docker run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n n8nio/n8n:latest
```

Open http://localhost:5678, create the owner account, then:

```bash
docker cp mock-credentials.json n8n:/tmp/creds.json
docker cp lead-capture-crm.json n8n:/tmp/wf.json
docker exec n8n n8n import:credentials --input=/tmp/creds.json
docker exec n8n n8n import:workflow --input=/tmp/wf.json
```

Or import `lead-capture-crm.json` from the n8n UI (*Workflows → Import from File*) and create the credentials yourself.

To regenerate the JSON after editing the generator:

```bash
python3 build_workflow.py
```

Tested with n8n 2.34.5.
