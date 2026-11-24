/*
  CDC_SeedDemoData
  Type: Interface (admin-only site page "Demo data")   |   Rule inputs: none

  Creates 12 customers, 28 complaints and their activity history. All dates
  are relative to today, so the dashboard always shows a realistic mix of
  on-track, due-soon and breached complaints.

  TIP: re-seed the day before the interview (Reset, then steps 2 and 3) so the
  deadlines land where the demo script expects them.

  Click the buttons in order. Each button runs one write, because each
  smart-service call needs its own button.
*/
a!localVariables(
  local!message: null,

  /* ---------------- Seed definitions ---------------- */
  local!customerSeed: {
    a!map(name: "Priya Shah", dob: date(1988, 3, 14), postcode: "LS6 2AB", segment: "Retail", vulnerable: false, driver: null, notes: null),
    a!map(name: "Tom Gallagher", dob: date(1979, 11, 2), postcode: "M20 4TT", segment: "Retail", vulnerable: false, driver: null, notes: null),
    a!map(name: "Margaret O'Neill", dob: date(1957, 6, 21), postcode: "BT9 5HG", segment: "Retail", vulnerable: true, driver: "Life event", notes: "Recently bereaved; acting as executor of her father's estate."),
    a!map(name: "David Okafor", dob: date(1983, 1, 30), postcode: "SE22 8LP", segment: "Premier", vulnerable: false, driver: null, notes: null),
    a!map(name: "Fiona MacLeod", dob: date(1991, 9, 9), postcode: "EH10 4QS", segment: "Retail", vulnerable: false, driver: null, notes: null),
    a!map(name: "Hamza Ali", dob: date(1975, 4, 17), postcode: "B12 9RT", segment: "SME", vulnerable: false, driver: null, notes: null),
    a!map(name: "Sarah Jenkins", dob: date(1996, 12, 5), postcode: "CF14 3NZ", segment: "Retail", vulnerable: false, driver: null, notes: null),
    a!map(name: "Liam Doyle", dob: date(1986, 7, 23), postcode: "BT7 1JL", segment: "Retail", vulnerable: true, driver: "Resilience", notes: "Made redundant last month; income has fallen sharply."),
    a!map(name: "Chloe Bennett", dob: date(1990, 2, 11), postcode: "BS8 1TH", segment: "Premier", vulnerable: false, driver: null, notes: null),
    a!map(name: "Grace Thompson", dob: date(1972, 8, 28), postcode: "NE1 7RU", segment: "Retail", vulnerable: true, driver: "Health", notes: "Long-term mental health condition; asked for written contact only."),
    a!map(name: "Arjun Patel", dob: date(1968, 5, 3), postcode: "LE1 6GH", segment: "SME", vulnerable: false, driver: null, notes: null),
    a!map(name: "Eileen Murphy", dob: date(1949, 10, 15), postcode: "BT7 3AD", segment: "Retail", vulnerable: true, driver: "Health", notes: "Hospitalised earlier this year; reduced capacity to manage her finances.")
  },
  local!complaintSeed: {
    a!map(cust: 1, ago: 0, channel: "Phone", product: "Current account", category: "Fraud and scams", pay: true, harm: "High", outcome: "Consumer support", status: "New", desc: "Lost £2,400 to an authorised push payment scam after a call from someone claiming to be the bank's fraud team. Wants reimbursement.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 2, ago: 1, channel: "Web form", product: "Credit card", category: "Fees and charges", pay: false, harm: "Medium", outcome: "Price and value", status: "Acknowledged", desc: "Charged a £12 late payment fee although the payment was made in the app on the due date.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 3, ago: 2, channel: "Letter", product: "Mortgage", category: "Communication", pay: false, harm: "High", outcome: "Consumer support", status: "Investigating", desc: "Executor of late father's estate. Asked for the death certificate three times; letters still addressed to the deceased.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 4, ago: 4, channel: "Email", product: "Home insurance", category: "Claims handling", pay: false, harm: "Medium", outcome: "Consumer support", status: "Investigating", desc: "Escape of water claim lodged 5 weeks ago and still no loss adjuster visit. Kitchen unusable.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 5, ago: 6, channel: "Phone", product: "Savings", category: "Communication", pay: false, harm: "Medium", outcome: "Consumer understanding", status: "Summary resolution", desc: "Fixed-rate bond matured and funds moved to an easy access account paying 1.1% without the customer being told.", decision: "Upheld", redress: 25, root: "Communication", after: 1),
    a!map(cust: 6, ago: 9, channel: "Social media", product: "Current account", category: "Service", pay: true, harm: "Low", outcome: "Consumer support", status: "Summary resolution", desc: "Branch closed early without notice, so the business could not deposit cash takings.", decision: "Not upheld", redress: 0, root: "No fault found", after: 1),
    a!map(cust: 7, ago: 12, channel: "Web form", product: "Motor insurance", category: "Fees and charges", pay: false, harm: "Medium", outcome: "Price and value", status: "Investigating", desc: "Renewal premium up 38% with no claims. Customer believes renewal pricing rules have been breached.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 8, ago: 15, channel: "Phone", product: "Personal loan", category: "Arrears handling", pay: false, harm: "High", outcome: "Consumer support", status: "Investigating", desc: "Lost job last month and asked for a payment holiday. Says the agent was dismissive and threatened default.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 4, ago: 20, channel: "Email", product: "Payments", category: "Payment delay", pay: true, harm: "Medium", outcome: "Consumer support", status: "Investigating", desc: "International payment of €8,500 for a house deposit held for 9 days for checks with no updates.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 9, ago: 25, channel: "Branch", product: "Mortgage", category: "Mis-selling", pay: false, harm: "High", outcome: "Products and services", status: "Investigating", desc: "Adviser recommended a 5-year fix although customer said they would sell within 2 years. Now faces a £6,200 early repayment charge.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 2, ago: 30, channel: "Letter", product: "Credit card", category: "Communication", pay: false, harm: "Medium", outcome: "Consumer understanding", status: "Final response issued", desc: "0% balance transfer ended earlier than expected; promotional terms were unclear in the app.", decision: "Partially upheld", redress: 75, root: "Communication", after: 21),
    a!map(cust: 5, ago: 34, channel: "Phone", product: "Home insurance", category: "Claims handling", pay: false, harm: "High", outcome: "Consumer support", status: "Final response issued", desc: "Storm damage claim declined as wear and tear; an independent roofer disputes this.", decision: "Upheld", redress: 1850, root: "Process", after: 28),
    a!map(cust: 6, ago: 40, channel: "Web form", product: "Current account", category: "Fees and charges", pay: true, harm: "Low", outcome: "Price and value", status: "Final response issued", desc: "Unarranged overdraft charges applied while salary was delayed by employer.", decision: "Not upheld", redress: 0, root: "No fault found", after: 10),
    a!map(cust: 11, ago: 44, channel: "Email", product: "Savings", category: "Service", pay: false, harm: "Low", outcome: "Consumer support", status: "Summary resolution", desc: "ISA transfer from another provider took 6 weeks.", decision: "Upheld", redress: 30, root: "People", after: 2),
    a!map(cust: 7, ago: 50, channel: "Phone", product: "Motor insurance", category: "Claims handling", pay: false, harm: "Medium", outcome: "Consumer support", status: "Investigating", desc: "Car written off; settlement offer is £3,000 below market value based on comparable listings.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 10, ago: 52, channel: "Letter", product: "Mortgage", category: "Arrears handling", pay: false, harm: "High", outcome: "Consumer support", status: "Investigating", desc: "Repeated arrears calls after the customer asked for written contact only because of a mental health condition.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 8, ago: 54, channel: "Web form", product: "Personal loan", category: "Mis-selling", pay: false, harm: "Medium", outcome: "Products and services", status: "Acknowledged", desc: "Loan approved while customer was on benefits; affordability check appears inadequate.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 11, ago: 60, channel: "Phone", product: "Current account", category: "Fraud and scams", pay: true, harm: "High", outcome: "Consumer support", status: "Investigating", desc: "Card cloned abroad; £640 of disputed transactions not refunded.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 9, ago: 63, channel: "Email", product: "Home insurance", category: "Communication", pay: false, harm: "Low", outcome: "Consumer understanding", status: "Investigating", desc: "Policy documents did not make clear that accidental damage cover was an optional extra.", decision: null, redress: null, root: null, after: null),
    a!map(cust: 3, ago: 75, channel: "Letter", product: "Mortgage", category: "Fees and charges", pay: false, harm: "Medium", outcome: "Price and value", status: "Referred to FOS", desc: "Disputes a £995 product fee added to the mortgage balance.", decision: "Not upheld", redress: 0, root: "No fault found", after: 50),
    a!map(cust: 12, ago: 90, channel: "Phone", product: "Credit card", category: "Arrears handling", pay: false, harm: "High", outcome: "Consumer support", status: "Final response issued", desc: "Interest and charges continued while customer was in hospital despite notifying the bank.", decision: "Upheld", redress: 420, root: "People", after: 40),
    a!map(cust: 1, ago: 100, channel: "Web form", product: "Savings", category: "Fees and charges", pay: false, harm: "Medium", outcome: "Price and value", status: "Final response issued", desc: "Existing customers paid a lower rate than new customers on the same savings account.", decision: "Not upheld", redress: 0, root: "Product design", after: 60),
    a!map(cust: 12, ago: 110, channel: "Branch", product: "Current account", category: "Service", pay: true, harm: "Medium", outcome: "Consumer support", status: "Summary resolution", desc: "Branch staff refused to accept a registered power of attorney.", decision: "Upheld", redress: 50, root: "People", after: 1),
    a!map(cust: 6, ago: 120, channel: "Email", product: "Payments", category: "Payment delay", pay: true, harm: "Medium", outcome: "Consumer support", status: "Final response issued", desc: "Faster Payment to a builder delayed 3 days by a system outage; supplier charged a late fee.", decision: "Upheld", redress: 120, root: "System", after: 12),
    a!map(cust: 7, ago: 130, channel: "Phone", product: "Motor insurance", category: "Fees and charges", pay: false, harm: "Low", outcome: "Price and value", status: "Final response issued", desc: "£50 admin fee for a mid-term change of address.", decision: "Partially upheld", redress: 40, root: "Product design", after: 20),
    a!map(cust: 10, ago: 140, channel: "Letter", product: "Personal loan", category: "Communication", pay: false, harm: "Medium", outcome: "Consumer understanding", status: "Referred to FOS", desc: "Settlement figure quoted by phone differed from the written statement.", decision: "Partially upheld", redress: 150, root: "Communication", after: 55),
    a!map(cust: 1, ago: 8, channel: "Phone", product: "Credit card", category: "Fraud and scams", pay: true, harm: "High", outcome: "Consumer support", status: "Summary resolution", desc: "Unrecognised online card transactions; refund requested.", decision: "Upheld", redress: 310, root: "Third party", after: 2),
    a!map(cust: 4, ago: 3, channel: "Web form", product: "Home insurance", category: "Mis-selling", pay: false, harm: "Medium", outcome: "Products and services", status: "New", desc: "Sold a home emergency add-on the customer already had under another policy.", decision: null, redress: null, root: null, after: null)
  },

  /* ---------------- Current state ---------------- */
  local!customerIds: a!refreshVariable(
    value: a!queryRecordType(
      recordType: recordType!CDC Customer,
      fields: recordType!CDC Customer.fields.id,
      filters: a!queryFilter(field: recordType!CDC Customer.fields.email, operator: "ends with", value: "@example.com"),
      pagingInfo: a!pagingInfo(1, 100, a!sortInfo(field: recordType!CDC Customer.fields.id, ascending: true))
    ).data[recordType!CDC Customer.fields.id],
    refreshAlways: true
  ),
  local!demoComplaints: a!refreshVariable(
    value: a!queryRecordType(
      recordType: recordType!CDC Complaint,
      fields: {
        recordType!CDC Complaint.fields.id,
        recordType!CDC Complaint.fields.status,
        recordType!CDC Complaint.fields.receivedOn,
        recordType!CDC Complaint.fields.finalResponseOn,
        recordType!CDC Complaint.fields.closedOn,
        recordType!CDC Complaint.fields.decision
      },
      filters: a!queryFilter(field: recordType!CDC Complaint.fields.reference, operator: "starts with", value: "CMP-DEMO-"),
      pagingInfo: a!pagingInfo(1, 500)
    ).data,
    refreshAlways: true
  ),
  local!demoEvents: a!refreshVariable(
    value: if(
      a!isNullOrEmpty(local!demoComplaints),
      {},
      a!queryRecordType(
        recordType: recordType!CDC Complaint Event,
        fields: recordType!CDC Complaint Event.fields.id,
        filters: a!queryFilter(
          field: recordType!CDC Complaint Event.fields.complaintId,
          operator: "in",
          value: local!demoComplaints[recordType!CDC Complaint.fields.id]
        ),
        pagingInfo: a!pagingInfo(1, 2000)
      ).data
    ),
    refreshAlways: true
  ),

  /* ---------------- Records to write ---------------- */
  local!customerRecords: a!forEach(
    items: local!customerSeed,
    expression: recordType!CDC Customer(
      recordType!CDC Customer.fields.fullName: fv!item.name,
      recordType!CDC Customer.fields.dateOfBirth: fv!item.dob,
      recordType!CDC Customer.fields.email:
        lower(substitute(substitute(fv!item.name, " ", "."), "'", "")) & "@example.com",
      recordType!CDC Customer.fields.postcode: fv!item.postcode,
      recordType!CDC Customer.fields.segment: fv!item.segment,
      recordType!CDC Customer.fields.isVulnerable: fv!item.vulnerable,
      recordType!CDC Customer.fields.vulnerabilityDriver: fv!item.driver,
      recordType!CDC Customer.fields.vulnerabilityNotes: fv!item.notes,
      recordType!CDC Customer.fields.createdOn: now()
    )
  ),
  local!complaintRecords: a!forEach(
    items: local!complaintSeed,
    expression: a!localVariables(
      local!received: a!subtractDateTime(
        startDateTime: now(),
        days: fv!item.ago,
        hours: mod(fv!index * 3, 7)
      ),
      local!dl: rule!CDC_CalculateDeadlines(receivedOn: local!received, isPaymentService: fv!item.pay),
      local!respondedOn: if(isnull(fv!item.after), null, todate(local!received) + fv!item.after),
      local!isSummary: fv!item.status = "Summary resolution",
      recordType!CDC Complaint(
        recordType!CDC Complaint.fields.reference: "CMP-DEMO-" & text(fv!index, "000"),
        recordType!CDC Complaint.fields.customerId: index(local!customerIds, fv!item.cust, null),
        recordType!CDC Complaint.fields.receivedOn: local!received,
        recordType!CDC Complaint.fields.channel: fv!item.channel,
        recordType!CDC Complaint.fields.product: fv!item.product,
        recordType!CDC Complaint.fields.category: fv!item.category,
        recordType!CDC Complaint.fields.description: fv!item.desc,
        recordType!CDC Complaint.fields.isPaymentService: fv!item.pay,
        recordType!CDC Complaint.fields.harmLevel: fv!item.harm,
        recordType!CDC Complaint.fields.consumerDutyOutcome: fv!item.outcome,
        recordType!CDC Complaint.fields.status: fv!item.status,
        recordType!CDC Complaint.fields.ownerUsername: loggedInUser(),
        recordType!CDC Complaint.fields.acknowledgedOn:
          if(fv!item.status = "New", null, a!addDateTime(startDateTime: local!received, hours: 2)),
        recordType!CDC Complaint.fields.summaryResolutionDueOn: local!dl.summaryResolutionDue,
        recordType!CDC Complaint.fields.finalResponseDueOn: local!dl.finalResponseDue,
        recordType!CDC Complaint.fields.finalResponseOn: if(local!isSummary, null, local!respondedOn),
        recordType!CDC Complaint.fields.decision: fv!item.decision,
        recordType!CDC Complaint.fields.redressAmount: fv!item.redress,
        recordType!CDC Complaint.fields.rootCause: fv!item.root,
        recordType!CDC Complaint.fields.closedOn: local!respondedOn,
        recordType!CDC Complaint.fields.createdOn: local!received
      )
    )
  ),
  local!eventRecords: a!flatten(
    a!forEach(
      items: local!demoComplaints,
      expression: a!localVariables(
        local!id: fv!item[recordType!CDC Complaint.fields.id],
        local!rec: fv!item[recordType!CDC Complaint.fields.receivedOn],
        local!status: fv!item[recordType!CDC Complaint.fields.status],
        local!user: loggedInUser(),
        local!mk: a!forEach(
          items: {
            a!map(show: true, type: "Complaint logged", detail: "Complaint received and logged", at: local!rec),
            a!map(
              show: local!status <> "New",
              type: "Acknowledgement sent",
              detail: "Written acknowledgement issued with complaints leaflet (DISP 1.6.1R)",
              at: a!addDateTime(startDateTime: local!rec, hours: 2)
            ),
            a!map(
              show: not(contains({"New", "Acknowledged"}, local!status)),
              type: "Customer contact",
              detail: "Called customer to understand the complaint and the outcome they want",
              at: a!addDateTime(startDateTime: local!rec, days: 1)
            ),
            a!map(
              show: local!status = "Summary resolution",
              type: "Final response sent",
              detail: "Summary resolution communication sent. Outcome: " & fv!item[recordType!CDC Complaint.fields.decision],
              at: todatetime(fv!item[recordType!CDC Complaint.fields.closedOn])
            ),
            a!map(
              show: contains({"Final response issued", "Referred to FOS"}, local!status),
              type: "Final response sent",
              detail: "Final response letter sent with FOS referral rights. Outcome: " & fv!item[recordType!CDC Complaint.fields.decision],
              at: todatetime(fv!item[recordType!CDC Complaint.fields.finalResponseOn])
            ),
            a!map(
              show: local!status = "Referred to FOS",
              type: "Referred to FOS",
              detail: "Financial Ombudsman Service notified us of a referral",
              at: a!addDateTime(startDateTime: todatetime(fv!item[recordType!CDC Complaint.fields.finalResponseOn]), days: 14)
            )
          },
          expression: if(
            fv!item.show,
            recordType!CDC Complaint Event(
              recordType!CDC Complaint Event.fields.complaintId: local!id,
              recordType!CDC Complaint Event.fields.eventType: fv!item.type,
              recordType!CDC Complaint Event.fields.detail: fv!item.detail,
              recordType!CDC Complaint Event.fields.createdBy: local!user,
              recordType!CDC Complaint Event.fields.createdOn: fv!item.at
            ),
            null
          )
        ),
        reject(fn!isnull, local!mk)
      )
    )
  ),

  /* ---------------- UI ---------------- */
  {
    a!richTextDisplayField(
      labelPosition: "COLLAPSED",
      value: {
        a!richTextItem(text: "Demo data", size: "LARGE", style: "STRONG"),
        char(10),
        a!richTextItem(
          text: "Demo customers: " & length(local!customerIds) &
            "   ·   Demo complaints: " & length(local!demoComplaints) &
            "   ·   Activity events: " & length(local!demoEvents),
          color: "SECONDARY"
        )
      }
    ),
    a!cardLayout(
      showWhen: not(isnull(local!message)),
      style: "SUCCESS",
      contents: a!richTextDisplayField(labelPosition: "COLLAPSED", value: local!message)
    ),
    a!sectionLayout(
      label: "Create",
      contents: a!buttonArrayLayout(
        align: "START",
        buttons: {
          a!buttonWidget(
            label: "1. Create customers",
            style: "OUTLINE",
            disabled: length(local!customerIds) > 0,
            saveInto: a!writeRecords(
              records: local!customerRecords,
              onSuccess: a!save(local!message, "Created " & length(fv!records) & " customers"),
              onError: a!save(local!message, "Could not create customers")
            )
          ),
          a!buttonWidget(
            label: "2. Create complaints",
            style: "OUTLINE",
            disabled: or(length(local!customerIds) < 12, length(local!demoComplaints) > 0),
            saveInto: a!writeRecords(
              records: local!complaintRecords,
              onSuccess: a!save(local!message, "Created " & length(fv!records) & " complaints"),
              onError: a!save(local!message, "Could not create complaints")
            )
          ),
          a!buttonWidget(
            label: "3. Create activity history",
            style: "OUTLINE",
            disabled: or(length(local!demoComplaints) = 0, length(local!demoEvents) > 0),
            saveInto: a!writeRecords(
              records: local!eventRecords,
              onSuccess: a!save(local!message, "Created " & length(fv!records) & " activity events"),
              onError: a!save(local!message, "Could not create activity")
            )
          )
        }
      )
    ),
    a!sectionLayout(
      label: "Reset (keeps customers)",
      contents: a!buttonArrayLayout(
        align: "START",
        buttons: {
          a!buttonWidget(
            label: "A. Delete demo activity",
            style: "OUTLINE",
            color: "NEGATIVE",
            disabled: length(local!demoEvents) = 0,
            saveInto: a!deleteRecords(
              records: local!demoEvents,
              onSuccess: a!save(local!message, "Deleted demo activity")
            )
          ),
          a!buttonWidget(
            label: "B. Delete demo complaints",
            style: "OUTLINE",
            color: "NEGATIVE",
            disabled: or(length(local!demoComplaints) = 0, length(local!demoEvents) > 0),
            saveInto: a!deleteRecords(
              records: local!demoComplaints,
              onSuccess: a!save(local!message, "Deleted demo complaints. Now run steps 2 and 3 again.")
            )
          )
        }
      )
    )
  }
)
