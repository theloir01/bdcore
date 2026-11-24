/*
  CDC_RecordOutcome
  Type: Interface (start form for the "Update complaint" related action)
  Rule inputs:
    complaint (CDC Complaint record type)  - passed in from the record action
    note      (Text)                       - written to the activity log
    cancel    (Boolean)

  Enforces the regulatory rules at the point of decision:
    - Summary resolution is only allowed up to the 3rd business day (DISP 1.5).
    - A final response needs an outcome and a root cause (DISP 1.3.3 RCA).
    - FOS referral only after a final response (or once the deadline has passed).
*/
a!localVariables(
  local!status: ri!complaint[recordType!CDC Complaint.fields.status],
  local!isFinal: local!status = "Final response issued",
  local!isSummary: local!status = "Summary resolution",
  local!isFos: local!status = "Referred to FOS",
  local!needsDecision: or(local!isFinal, local!isSummary),
  local!sla: rule!CDC_SlaStatus(
    dueDate: ri!complaint[recordType!CDC Complaint.fields.finalResponseDueOn],
    completedOn: ri!complaint[recordType!CDC Complaint.fields.finalResponseOn]
  ),
  a!formLayout(
    label: "Update " & ri!complaint[recordType!CDC Complaint.fields.reference],
    contents: {
      a!cardLayout(
        style: "NONE",
        showBorder: true,
        marginBelow: "STANDARD",
        contents: a!richTextDisplayField(
          labelPosition: "COLLAPSED",
          value: {
            a!richTextItem(text: "Final response due: ", style: "STRONG"),
            text(ri!complaint[recordType!CDC Complaint.fields.finalResponseDueOn], "ddd dd mmm yyyy"),
            "   ",
            a!richTextItem(text: " " & local!sla.label & " ", color: local!sla.color, style: "STRONG"),
            "  ",
            a!richTextItem(text: local!sla.detail, color: "SECONDARY")
          }
        )
      ),
      a!dropdownField(
        label: "Status",
        choiceLabels: rule!CDC_RefData("STATUS"),
        choiceValues: rule!CDC_RefData("STATUS"),
        value: local!status,
        saveInto: ri!complaint[recordType!CDC Complaint.fields.status],
        required: true,
        validations: {
          if(
            and(
              local!isSummary,
              today() > ri!complaint[recordType!CDC Complaint.fields.summaryResolutionDueOn]
            ),
            "The summary resolution window ended on " &
              text(ri!complaint[recordType!CDC Complaint.fields.summaryResolutionDueOn], "dd mmm yyyy") &
              ". Issue a final response instead (DISP 1.5).",
            null
          ),
          if(
            and(
              local!isFos,
              isnull(ri!complaint[recordType!CDC Complaint.fields.finalResponseOn]),
              today() <= ri!complaint[recordType!CDC Complaint.fields.finalResponseDueOn]
            ),
            "A FOS referral normally follows a final response, or comes after the deadline has passed.",
            null
          )
        }
      ),
      a!sectionLayout(
        label: "Decision",
        showWhen: or(local!needsDecision, local!isFos),
        contents: {
          a!columnsLayout(
            columns: {
              a!columnLayout(
                contents: a!radioButtonField(
                  label: "Outcome",
                  choiceLabels: rule!CDC_RefData("DECISION"),
                  choiceValues: rule!CDC_RefData("DECISION"),
                  value: ri!complaint[recordType!CDC Complaint.fields.decision],
                  saveInto: ri!complaint[recordType!CDC Complaint.fields.decision],
                  required: local!needsDecision
                )
              ),
              a!columnLayout(
                contents: {
                  a!dropdownField(
                    label: "Root cause",
                    placeholder: "Select a root cause",
                    choiceLabels: rule!CDC_RefData("ROOT_CAUSE"),
                    choiceValues: rule!CDC_RefData("ROOT_CAUSE"),
                    value: ri!complaint[recordType!CDC Complaint.fields.rootCause],
                    saveInto: ri!complaint[recordType!CDC Complaint.fields.rootCause],
                    required: local!isFinal,
                    instructions: "Feeds root cause analysis and Consumer Duty MI"
                  ),
                  a!floatingPointField(
                    label: "Redress paid (£)",
                    value: ri!complaint[recordType!CDC Complaint.fields.redressAmount],
                    saveInto: ri!complaint[recordType!CDC Complaint.fields.redressAmount],
                    validations: if(
                      a!defaultValue(ri!complaint[recordType!CDC Complaint.fields.redressAmount], 0) < 0,
                      "Redress cannot be negative",
                      null
                    )
                  )
                }
              )
            }
          ),
          a!dateField(
            label: "Final response sent on",
            showWhen: local!isFinal,
            value: ri!complaint[recordType!CDC Complaint.fields.finalResponseOn],
            saveInto: ri!complaint[recordType!CDC Complaint.fields.finalResponseOn],
            required: local!isFinal
          )
        }
      ),
      a!paragraphField(
        label: "Note for the activity log",
        value: ri!note,
        saveInto: ri!note,
        characterLimit: 255,
        height: "SHORT"
      )
    },
    buttons: a!buttonLayout(
      primaryButtons: a!buttonWidget(
        label: "Save",
        style: "SOLID",
        submit: true,
        validate: true,
        saveInto: {
          a!save(
            ri!complaint[recordType!CDC Complaint.fields.closedOn],
            if(
              or(local!isSummary, local!isFinal, local!status = "Closed"),
              a!defaultValue(ri!complaint[recordType!CDC Complaint.fields.closedOn], today()),
              null
            )
          )
        }
      ),
      secondaryButtons: a!buttonWidget(
        label: "Cancel",
        style: "LINK",
        submit: true,
        validate: false,
        value: true,
        saveInto: ri!cancel
      )
    )
  )
)
