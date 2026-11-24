# Demo script: Consumer Duty Complaints Hub (about 10 minutes)

## 0. Set-up (before the call)
- Re-seed the demo data the day before.
- Open three browser tabs: the **Dashboard**, the **Complaints** record list, and the record
  for **CMP-DEMO-016** (Grace Thompson, the arrears complaint).
- Zoom the browser to about 110%. Close every other tab and notification.

## 1. The problem (1 min, no screen)
> "Since July 2023, Consumer Duty means firms have to *evidence* good outcomes, and
> complaints are one of the best signals they have. But in most firms complaints sit in a
> CRM or spreadsheets, the DISP deadlines are tracked by hand, and the root-cause data never
> reaches product or pricing teams. Breaching the 8-week deadline gives the customer an
> automatic route to the Ombudsman, at £650 a case in fees, whatever the outcome."

(Check the current FOS case fee before the interview. It changes from year to year.)

## 2. Dashboard (2 min)
- **KPI tiles:** "Two breached, several due this week. A team leader sees this the moment
  they log in."
- **Outcome by harm chart:** "Every complaint is tagged against one of the four Consumer Duty
  outcomes, which is the evidence a board report needs."
- **Root causes:** "This is the DISP 1.3 root cause analysis. It tells product owners *why*,
  not just how many."
- **Work queue:** sorted by deadline, with the vulnerable-customer icon. Click into the most
  urgent complaint.

## 3. A complaint record (2 min): CMP-DEMO-016
- **Vulnerability banner:** "FG21/1 says firms must recognise and act on vulnerability. Here
  it's on every screen, not buried in notes."
- **Deadline tiles:** "The regulatory clock is calculated for you, including bank holidays,
  and switches to the 15-business-day payment services rule automatically."
- **Activity timeline:** the audit trail.

## 4. Log a new complaint live (3 min)
Use **Log complaint** with customer **Liam Doyle**, received today, channel Phone, product
Personal loan, category Arrears handling. Type:

> *"Lost my job and asked for help with repayments but was told I'd be passed to collections
> and charged a default fee."*

Point out:
1. The vulnerability banner appears as soon as you pick the customer.
2. The deadlines calculate as you type.
3. **Suggested triage** shows *High harm, Consumer support*, with its reasons. Click
   **Apply suggestion**. "This is transparent, rule-based triage. The same slot takes an
   AI classifier, and the handler stays in control."

Submit. The record opens with status *Acknowledged* and an acknowledgement event in its
history.

## 5. Close a complaint (1 min)
On **CMP-DEMO-009** (the €8,500 payment that's due soon), use **Update complaint**:
- Try *Summary resolution*. It's **blocked**, because the 3-business-day window has passed:
  "the rules enforce DISP, not just display it."
- Choose *Final response issued*, Partially upheld, root cause Process, redress £150.
  Root cause is mandatory.

Go back to the dashboard. The numbers have changed.

## 6. What I'd do next (1 min)
- **Integrate** with core banking and CRM through Appian integrations and data fabric, so the
  customer and product data are live instead of copied.
- **AI:** classify inbound emails and letters with document extraction, and suggest a
  drafted final response.
- **Process insights:** find where complaints wait, using process mining.
- **UK&I:** Scottish and NI bank-holiday calendars; Central Bank of Ireland rules (the Consumer
  Protection Code's 40-business-day final response) for Irish entities.
- **Regulatory reporting:** the half-yearly FCA complaints return, generated from the same data.

## Talking points if they ask "why Appian?"
- **One platform:** data, process, rules, UI and reporting together, so a compliance change
  (for example a new DISP rule) is a configuration change, not a project.
- **Speed:** "I built this on Community Edition in a few evenings."
- **Auditability:** every action and decision is recorded, which is what the FCA asks firms
  to evidence.
- **Human and AI together:** AI suggests, people decide, and the system records both.

## Questions to have answers ready for
- *How would you handle complaints received out of hours?* DISP allows treating them as received
  the next business day. It's a one-line change in `CDC_CalculateDeadlines`.
- *Who can see vulnerability data?* It's special category data, so in production I'd restrict
  it with record-level security, use it only where it helps the customer, and log access.
- *How does it scale?* Record types sync with external databases, the processes run in
  parallel, and the deadline logic is a reusable rule other apps can call.
