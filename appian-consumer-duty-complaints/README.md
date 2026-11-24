# Consumer Duty Complaints Hub: Appian build pack

A complaints-handling app for a UK bank or insurer, built on **Appian Community Edition**.
It tracks the FCA DISP deadlines automatically, flags vulnerable customers, suggests triage,
and gives a live Consumer Duty MI dashboard.

**The pitch in one line:** *"Every UK firm has to evidence good customer outcomes under
Consumer Duty. This shows how Appian turns complaints from a compliance cost into
outcome data, with the regulatory clock built in."*

| Folder | What's in it |
|---|---|
| `rules/` | Expression rules: bank holidays, reference data, DISP deadline engine, SLA status, triage |
| `interfaces/` | SAIL for the log-complaint form, update form, record summary view, MI dashboard, demo-data page |
| `DEMO-SCRIPT.md` | A 10-minute demo running order and interview talking points |

> **Status:** written against current Appian SAIL syntax but **not yet run on a live site**.
> Expect to fix a few small things as you paste it in (a field name you typed differently,
> an icon name, a parameter your version doesn't support). Paste the error back to Claude
> and it's usually a one-line fix.

---

## The regulatory rules the app encodes

| Rule | Source | How the app uses it |
|---|---|---|
| Prompt written acknowledgement | DISP 1.6.1R | The log-complaint process sets status *Acknowledged* and records the event |
| Summary resolution by close of the **3rd business day** after receipt | DISP 1.5 | `summaryResolutionDueOn`; the update form blocks a summary resolution after this date |
| Final response within **8 weeks** | DISP 1.6.2R | `finalResponseDueOn` = received + 56 days |
| Payment services: **15 business days**, 35 if exceptional | DISP 1.6.2A (PSRs 2017) | Switches automatically when *Payment service complaint* is ticked |
| Root cause analysis | DISP 1.3.3R | Root cause required on a final response; feeds the dashboard |
| Fair treatment of vulnerable customers | FCA FG21/1 | Vulnerability flag and drivers on the customer, shown on every screen |
| Consumer Duty four outcomes | PRIN 2A | Every complaint tagged with one outcome, reported on the dashboard |

Business days use England & Wales bank holidays (`CDC_UkBankHolidays`). Scotland and
Northern Ireland differ, which is a good "what I'd do next" point.

---

## Build order

Allow **3 sessions of about 2 to 3 hours each**. Each phase ends with something you could
already demo.

### Phase 1: data and rules (session 1)

**1. Create the application**
- Appian Designer → **New Application** → name `Consumer Duty Complaints`, prefix `CDC`.
- Create groups `CDC Administrators` and `CDC Complaint Handlers`, and add yourself to both.

**2. Create three record types**, each with **New → Record Type → "Create a new data model"**
so that Appian manages the table and you need no database.

Use these field names exactly, because the SAIL refers to them. Appian adds `id` (the
primary key) automatically. Set text fields to the largest length your version offers, at
least 255.

**`CDC Customer`**

| Field | Type |
|---|---|
| `id` | Integer (PK, auto) |
| `fullName` | Text |
| `dateOfBirth` | Date |
| `email` | Text |
| `postcode` | Text |
| `segment` | Text |
| `isVulnerable` | Boolean |
| `vulnerabilityDriver` | Text |
| `vulnerabilityNotes` | Text |
| `createdOn` | Date and Time |

**`CDC Complaint`**

| Field | Type | Notes |
|---|---|---|
| `id` | Integer (PK, auto) | |
| `reference` | Text | `CMP-…` |
| `customerId` | Integer | Links to CDC Customer |
| `receivedOn` | Date and Time | |
| `channel` | Text | |
| `product` | Text | |
| `category` | Text | |
| `description` | Text | |
| `isPaymentService` | Boolean | Switches on the 15-business-day rule |
| `harmLevel` | Text | Low / Medium / High |
| `consumerDutyOutcome` | Text | One of the four outcomes |
| `status` | Text | |
| `ownerUsername` | Text | |
| `acknowledgedOn` | Date and Time | |
| `summaryResolutionDueOn` | Date | |
| `finalResponseDueOn` | Date | |
| `finalResponseOn` | Date | |
| `decision` | Text | Upheld / Partially upheld / Not upheld |
| `redressAmount` | Decimal | |
| `rootCause` | Text | |
| `closedOn` | Date | |
| `createdOn` | Date and Time | |

**`CDC Complaint Event`**

| Field | Type |
|---|---|
| `id` | Integer (PK, auto) |
| `complaintId` | Integer |
| `eventType` | Text |
| `detail` | Text |
| `createdBy` | Text |
| `createdOn` | Date and Time |

**3. Add relationships** (on each record type's *Relationships* tab, using the existing fields):

| On | Relationship name | Type | Join |
|---|---|---|---|
| CDC Complaint | `customer` | many-to-one → CDC Customer | `customerId` = `id` |
| CDC Complaint | `events` | one-to-many → CDC Complaint Event | `id` = `complaintId` |
| CDC Customer | `complaints` | one-to-many → CDC Complaint | `id` = `customerId` |

The relationship name `customer` matters: the SAIL uses
`recordType!CDC Complaint.relationships.customer.fields.…`.

**4. Create the expression rules** from `rules/`. Add each rule input listed in the file
header, then paste in the body. Do them in this order, because later rules call earlier ones:
1. `CDC_UkBankHolidays`
2. `CDC_RefData`
3. `CDC_CalculateDeadlines`
4. `CDC_SlaStatus`
5. `CDC_SuggestTriage`

Test each one in the rule's test panel. For example, `CDC_CalculateDeadlines` with
`receivedOn` = 23 Dec 2026 10:00 and `isPaymentService` = true should give a summary
resolution due date of **30 Dec 2026**.

**5. Load the demo data.** Create the interface `CDC_SeedDemoData` from
`interfaces/CDC_SeedDemoData.sail`. In its preview, click **1 → 2 → 3**. You now have
12 customers, 28 complaints and their activity history.

### Phase 2: records and forms (session 2)

**6. Configure the CDC Complaint record type**
- **Record title:** `rv!record[recordType!CDC Complaint.fields.reference] & " · " & rv!record[recordType!CDC Complaint.fields.product]`
- **Record list columns:** Reference, Customer (`customer.fullName`), Product, Harm, Status,
  Final response due. Sort by Final response due, ascending.
- **User filters:** Status, Product, Harm level, Consumer Duty outcome, Category.
- **Summary view:** create the interface `CDC_ComplaintSummary` (rule inputs `record` of type
  CDC Complaint and `identifier` of type Integer), then set the view to
  `rule!CDC_ComplaintSummary(record: rv!record, identifier: rv!identifier)`.

Configure `CDC Customer` the same way, more simply. A grid of the customer's complaints on
its summary view is a nice extra.

**7. Create the interfaces** `CDC_LogComplaint` and `CDC_RecordOutcome` from `interfaces/`
(rule inputs are in each file header).

**8. Process model: `CDC Log Complaint`** (record list action **"Log complaint"**)

Shortcut: on the record type's *Actions* tab, choose **Generate record actions**. Appian
builds a create process and an update process plus forms. Then swap in these forms and add
the extra nodes below.

| # | Node | Configuration |
|---|---|---|
| | Process variables | `complaint` (CDC Complaint, parameter), `event` (CDC Complaint Event), `cancel` (Boolean) |
| 1 | **Start form** | `CDC_LogComplaint`: `ri!complaint` → `pv!complaint`, `ri!cancel` → `pv!cancel` |
| 2 | XOR gateway | If `pv!cancel` → End |
| 3 | Script task *"Acknowledge"* | Two outputs, each targeting a field of `pv!complaint` in the target picker: `status` = `"Acknowledged"`, `acknowledgedOn` = `now()` |
| 4 | **Write Records** | Records: `pv!complaint`. Output: stored values → `pv!complaint`, so you get the new `id` |
| 5 | Script task *"Build event"* | `pv!event` = `recordType!CDC Complaint Event(recordType!CDC Complaint Event.fields.complaintId: pv!complaint[recordType!CDC Complaint.fields.id], …eventType: "Acknowledgement sent", …detail: "Written acknowledgement issued (DISP 1.6.1R)", …createdBy: pp!initiator, …createdOn: now())` |
| 6 | **Write Records** | Records: `pv!event` |
| 7 | End | Turn on activity chaining from the start form through node 6, so the user lands straight on the new record |

**9. Process model: `CDC Update Complaint`** (record **related action** "Update complaint")

| # | Node | Configuration |
|---|---|---|
| | Process variables | `complaint` (CDC Complaint, parameter), `note` (Text), `cancel` (Boolean), `event` |
| 1 | **Start form** | `CDC_RecordOutcome` |
| 2 | XOR gateway | If `pv!cancel` → End |
| 3 | **Write Records** | `pv!complaint` |
| 4 | Script task | Build `pv!event` with `eventType` = `if(pv!complaint[recordType!CDC Complaint.fields.status] = "Final response issued", "Final response sent", "Status change")` and `detail` = `"Status: " & pv!complaint[recordType!CDC Complaint.fields.status] & if(isnull(pv!note), "", " · " & pv!note)` |
| 5 | **Write Records** | `pv!event` |

In the record action's configuration, pass `rv!record` to the `complaint` parameter.
Limit both actions to `CDC Complaint Handlers`.

### Phase 3: dashboard, site and polish (session 3)

**10. Create the interface `CDC_ComplianceDashboard`.**

**11. Create a site** called `Complaints Hub`, with these pages:

| Page | Content | Visible to |
|---|---|---|
| Dashboard | `CDC_ComplianceDashboard` | Everyone |
| Complaints | CDC Complaint record list | Everyone |
| Customers | CDC Customer record list | Everyone |
| Demo data | `CDC_SeedDemoData` | CDC Administrators only |

Pick a dark navy header colour and a short display name. It makes a big difference on screen.

**12. Rehearse** with `DEMO-SCRIPT.md`. **Re-seed the day before the interview** (Reset A → B,
then 2 → 3) so the dates line up with the demo script.

### Stretch goals (if you have time)

- **Escalation:** give the update process a user task assigned to `CDC Complaint Handlers`,
  with a timer escalation 5 business days before `finalResponseDueOn` that reassigns the task
  to a team leader and logs an event. This shows Appian's process engine, not just forms.
- **AI triage:** if your site has Appian AI skills, swap `CDC_SuggestTriage` for an AI
  classification of the description. Keep the "reasons" panel and the *Apply* button, so a
  human stays in the loop. That's a strong talking point.
- **Process HQ / process insights**, if available on Community Edition: show where complaints
  wait longest.
- **FCA complaints return:** add a report grouped by product and decision that mirrors the
  DISP 1 Annex 1 return.
