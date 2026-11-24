/*
  CDC_ComplaintSummary
  Type: Interface, used as the Summary view of the CDC Complaint record type.
  In the record type's Views tab set the Summary view to:
      rule!CDC_ComplaintSummary(record: rv!record, identifier: rv!identifier)
  Rule inputs:
    record      (CDC Complaint record type)
    identifier  (Integer)
*/
a!localVariables(
  local!r: ri!record,
  local!status: local!r[recordType!CDC Complaint.fields.status],
  local!isOpen: contains(rule!CDC_RefData("OPEN_STATUS"), local!status),
  local!srcSla: if(
    or(local!isOpen, local!status = "Summary resolution"),
    rule!CDC_SlaStatus(
      dueDate: local!r[recordType!CDC Complaint.fields.summaryResolutionDueOn],
      completedOn: if(
        local!status = "Summary resolution",
        local!r[recordType!CDC Complaint.fields.closedOn],
        null
      )
    ),
    a!map(label: "Not used", color: "#5F6B7A", detail: "Resolved by final response")
  ),
  local!frSla: rule!CDC_SlaStatus(
    dueDate: local!r[recordType!CDC Complaint.fields.finalResponseDueOn],
    completedOn: if(
      local!status = "Summary resolution",
      local!r[recordType!CDC Complaint.fields.closedOn],
      local!r[recordType!CDC Complaint.fields.finalResponseOn]
    )
  ),
  local!harmColor: a!match(
    value: local!r[recordType!CDC Complaint.fields.harmLevel],
    equals: "High", then: "#C62828",
    equals: "Medium", then: "#B25E09",
    default: "#1E7B3A"
  ),
  local!isVulnerable: a!defaultValue(
    local!r[recordType!CDC Complaint.relationships.customer.fields.isVulnerable],
    false
  ),
  local!milestones: {"Received", "Acknowledged", "Investigating", "Responded", "Closed"},
  local!milestoneIndex: a!match(
    value: local!status,
    equals: "New", then: 1,
    equals: "Acknowledged", then: 2,
    equals: "Investigating", then: 3,
    equals: "Summary resolution", then: 5,
    equals: "Final response issued", then: 4,
    equals: "Referred to FOS", then: 4,
    default: 5
  ),
  {
    /* ---------- Status strip ---------- */
    a!columnsLayout(
      columns: {
        a!columnLayout(
          contents: a!tagField(
            labelPosition: "COLLAPSED",
            size: "STANDARD",
            tags: {
              a!tagItem(text: local!status, backgroundColor: "#2B4C7E"),
              a!tagItem(
                text: local!r[recordType!CDC Complaint.fields.harmLevel] & " harm",
                backgroundColor: local!harmColor
              ),
              a!tagItem(
                text: local!r[recordType!CDC Complaint.fields.consumerDutyOutcome],
                backgroundColor: "#5B3F8C"
              ),
              if(
                a!defaultValue(local!r[recordType!CDC Complaint.fields.isPaymentService], false),
                a!tagItem(text: "Payment services (PSRs)", backgroundColor: "#5F6B7A"),
                {}
              ),
              if(
                local!isVulnerable,
                a!tagItem(text: "Vulnerable customer", backgroundColor: "#C62828"),
                {}
              )
            }
          )
        )
      }
    ),
    a!milestoneField(
      labelPosition: "COLLAPSED",
      steps: local!milestones,
      active: local!milestoneIndex
    ),

    /* ---------- SLA tiles ---------- */
    a!columnsLayout(
      marginBelow: "STANDARD",
      columns: a!forEach(
        items: {
          a!map(
            title: "Summary resolution (DISP 1.5)",
            due: local!r[recordType!CDC Complaint.fields.summaryResolutionDueOn],
            sla: local!srcSla
          ),
          a!map(
            title: if(
              a!defaultValue(local!r[recordType!CDC Complaint.fields.isPaymentService], false),
              "Final response (15 business days)",
              "Final response (8 weeks)"
            ),
            due: local!r[recordType!CDC Complaint.fields.finalResponseDueOn],
            sla: local!frSla
          )
        },
        expression: a!columnLayout(
          contents: a!cardLayout(
            showBorder: true,
            decorativeBarPosition: "TOP",
            decorativeBarColor: fv!item.sla.color,
            contents: a!richTextDisplayField(
              labelPosition: "COLLAPSED",
              value: {
                a!richTextItem(text: fv!item.title, color: "SECONDARY"),
                char(10),
                a!richTextItem(text: text(fv!item.due, "ddd dd mmm yyyy"), size: "MEDIUM_PLUS", style: "STRONG"),
                char(10),
                a!richTextItem(text: fv!item.sla.label, color: fv!item.sla.color, style: "STRONG"),
                if(a!isNullOrEmpty(fv!item.sla.detail), "", "  ·  " & fv!item.sla.detail)
              }
            )
          )
        )
      )
    ),

    a!columnsLayout(
      columns: {
        /* ---------- Complaint details ---------- */
        a!columnLayout(
          width: "WIDE",
          contents: {
            a!sectionLayout(
              label: "Complaint",
              contents: {
                a!richTextDisplayField(
                  label: "What the customer told us",
                  value: local!r[recordType!CDC Complaint.fields.description]
                ),
                a!sideBySideLayout(
                  items: {
                    a!sideBySideItem(item: a!textField(label: "Product", readOnly: true, value: local!r[recordType!CDC Complaint.fields.product])),
                    a!sideBySideItem(item: a!textField(label: "Category", readOnly: true, value: local!r[recordType!CDC Complaint.fields.category])),
                    a!sideBySideItem(item: a!textField(label: "Channel", readOnly: true, value: local!r[recordType!CDC Complaint.fields.channel])),
                    a!sideBySideItem(
                      item: a!textField(
                        label: "Received",
                        readOnly: true,
                        value: text(local!r[recordType!CDC Complaint.fields.receivedOn], "dd mmm yyyy hh:mm")
                      )
                    )
                  }
                )
              }
            ),
            a!sectionLayout(
              label: "Outcome",
              showWhen: not(local!isOpen),
              contents: a!sideBySideLayout(
                items: {
                  a!sideBySideItem(item: a!textField(label: "Decision", readOnly: true, value: local!r[recordType!CDC Complaint.fields.decision])),
                  a!sideBySideItem(item: a!textField(label: "Root cause", readOnly: true, value: local!r[recordType!CDC Complaint.fields.rootCause])),
                  a!sideBySideItem(
                    item: a!textField(
                      label: "Redress",
                      readOnly: true,
                      value: "£" & fixed(a!defaultValue(local!r[recordType!CDC Complaint.fields.redressAmount], 0), 2)
                    )
                  )
                }
              )
            ),
            a!sectionLayout(
              label: "Activity",
              contents: a!gridField(
                labelPosition: "COLLAPSED",
                emptyGridMessage: "No activity recorded yet",
                data: a!recordData(
                  recordType: recordType!CDC Complaint Event,
                  filters: a!queryFilter(
                    field: recordType!CDC Complaint Event.fields.complaintId,
                    operator: "=",
                    value: ri!identifier
                  )
                ),
                initialSorts: a!sortInfo(field: recordType!CDC Complaint Event.fields.createdOn, ascending: false),
                pageSize: 10,
                columns: {
                  a!gridColumn(
                    label: "When",
                    sortField: recordType!CDC Complaint Event.fields.createdOn,
                    value: text(fv!row[recordType!CDC Complaint Event.fields.createdOn], "dd mmm yyyy hh:mm"),
                    width: "NARROW_PLUS"
                  ),
                  a!gridColumn(
                    label: "Event",
                    value: a!richTextDisplayField(
                      value: a!richTextItem(text: fv!row[recordType!CDC Complaint Event.fields.eventType], style: "STRONG")
                    ),
                    width: "NARROW_PLUS"
                  ),
                  a!gridColumn(label: "Detail", value: fv!row[recordType!CDC Complaint Event.fields.detail]),
                  a!gridColumn(
                    label: "By",
                    value: fv!row[recordType!CDC Complaint Event.fields.createdBy],
                    width: "NARROW"
                  )
                }
              )
            )
          }
        ),

        /* ---------- Customer card ---------- */
        a!columnLayout(
          width: "MEDIUM",
          contents: {
            a!cardLayout(
              style: "WARN",
              showWhen: local!isVulnerable,
              marginBelow: "STANDARD",
              contents: a!richTextDisplayField(
                labelPosition: "COLLAPSED",
                value: {
                  a!richTextIcon(icon: "exclamation-triangle"),
                  a!richTextItem(text: "  Vulnerability: ", style: "STRONG"),
                  local!r[recordType!CDC Complaint.relationships.customer.fields.vulnerabilityDriver],
                  char(10),
                  local!r[recordType!CDC Complaint.relationships.customer.fields.vulnerabilityNotes],
                  char(10),
                  a!richTextItem(
                    text: "Adapt communications and timelines (FCA FG21/1).",
                    color: "SECONDARY",
                    size: "SMALL"
                  )
                }
              )
            ),
            a!sectionLayout(
              label: "Customer",
              contents: {
                a!richTextDisplayField(
                  labelPosition: "COLLAPSED",
                  value: a!richTextItem(
                    text: local!r[recordType!CDC Complaint.relationships.customer.fields.fullName],
                    size: "MEDIUM",
                    style: "STRONG",
                    link: a!recordLink(
                      recordType: recordType!CDC Customer,
                      identifier: local!r[recordType!CDC Complaint.fields.customerId]
                    )
                  )
                ),
                a!textField(label: "Segment", readOnly: true, value: local!r[recordType!CDC Complaint.relationships.customer.fields.segment]),
                a!textField(label: "Postcode", readOnly: true, value: local!r[recordType!CDC Complaint.relationships.customer.fields.postcode]),
                a!textField(label: "Complaint owner", readOnly: true, value: local!r[recordType!CDC Complaint.fields.ownerUsername])
              }
            )
          }
        )
      }
    )
  }
)
