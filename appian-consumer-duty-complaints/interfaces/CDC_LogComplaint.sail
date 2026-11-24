/*
  CDC_LogComplaint
  Type: Interface (start form for the "Log complaint" record action)
  Rule inputs:
    complaint (CDC Complaint record type)
    cancel    (Boolean)

  Shows live DISP deadlines and a triage suggestion while the handler types.
*/
a!localVariables(
  local!customer: if(
    isnull(ri!complaint[recordType!CDC Complaint.fields.customerId]),
    null,
    a!queryRecordByIdentifier(
      recordType: recordType!CDC Customer,
      identifier: ri!complaint[recordType!CDC Complaint.fields.customerId],
      fields: {
        recordType!CDC Customer.fields.fullName,
        recordType!CDC Customer.fields.isVulnerable,
        recordType!CDC Customer.fields.vulnerabilityDriver,
        recordType!CDC Customer.fields.vulnerabilityNotes
      }
    )
  ),
  local!isVulnerable: a!defaultValue(
    index(local!customer, recordType!CDC Customer.fields.isVulnerable, false),
    false
  ),
  local!deadlines: rule!CDC_CalculateDeadlines(
    receivedOn: ri!complaint[recordType!CDC Complaint.fields.receivedOn],
    isPaymentService: ri!complaint[recordType!CDC Complaint.fields.isPaymentService]
  ),
  local!triage: rule!CDC_SuggestTriage(
    category: ri!complaint[recordType!CDC Complaint.fields.category],
    description: ri!complaint[recordType!CDC Complaint.fields.description],
    isVulnerable: local!isVulnerable
  ),
  a!formLayout(
    label: "Log a complaint",
    instructions: "Record the complaint as the customer described it. Deadlines are calculated automatically under DISP 1.5 and 1.6.",
    contents: {
      a!columnsLayout(
        columns: {
          /* ---------------- Left: complaint details ---------------- */
          a!columnLayout(
            width: "WIDE",
            contents: {
              a!sectionLayout(
                label: "Customer",
                contents: {
                  a!pickerFieldRecords(
                    label: "Customer",
                    recordType: recordType!CDC Customer,
                    maxSelections: 1,
                    value: ri!complaint[recordType!CDC Complaint.fields.customerId],
                    saveInto: a!save(
                      ri!complaint[recordType!CDC Complaint.fields.customerId],
                      index(save!value, 1, null)
                    ),
                    required: true
                  ),
                  a!cardLayout(
                    showWhen: local!isVulnerable,
                    style: "WARN",
                    contents: a!richTextDisplayField(
                      labelPosition: "COLLAPSED",
                      value: {
                        a!richTextIcon(icon: "exclamation-triangle"),
                        a!richTextItem(text: "  Vulnerable customer: ", style: "STRONG"),
                        index(local!customer, recordType!CDC Customer.fields.vulnerabilityDriver, ""),
                        char(10),
                        a!richTextItem(
                          text: index(local!customer, recordType!CDC Customer.fields.vulnerabilityNotes, ""),
                          color: "SECONDARY"
                        )
                      }
                    ),
                    marginBelow: "STANDARD"
                  )
                }
              ),
              a!sectionLayout(
                label: "Complaint",
                contents: {
                  a!sideBySideLayout(
                    items: {
                      a!sideBySideItem(
                        item: a!dateTimeField(
                          label: "Received",
                          value: ri!complaint[recordType!CDC Complaint.fields.receivedOn],
                          saveInto: ri!complaint[recordType!CDC Complaint.fields.receivedOn],
                          required: true
                        )
                      ),
                      a!sideBySideItem(
                        item: a!dropdownField(
                          label: "Channel",
                          placeholder: "Select a channel",
                          choiceLabels: rule!CDC_RefData("CHANNEL"),
                          choiceValues: rule!CDC_RefData("CHANNEL"),
                          value: ri!complaint[recordType!CDC Complaint.fields.channel],
                          saveInto: ri!complaint[recordType!CDC Complaint.fields.channel],
                          required: true
                        )
                      )
                    }
                  ),
                  a!sideBySideLayout(
                    items: {
                      a!sideBySideItem(
                        item: a!dropdownField(
                          label: "Product",
                          placeholder: "Select a product",
                          choiceLabels: rule!CDC_RefData("PRODUCT"),
                          choiceValues: rule!CDC_RefData("PRODUCT"),
                          value: ri!complaint[recordType!CDC Complaint.fields.product],
                          saveInto: {
                            ri!complaint[recordType!CDC Complaint.fields.product],
                            /* Default the payment-services flag from the product */
                            a!save(
                              ri!complaint[recordType!CDC Complaint.fields.isPaymentService],
                              contains(rule!CDC_RefData("PAYMENT_PRODUCTS"), save!value)
                            )
                          },
                          required: true
                        )
                      ),
                      a!sideBySideItem(
                        item: a!dropdownField(
                          label: "Category",
                          placeholder: "Select a category",
                          choiceLabels: rule!CDC_RefData("CATEGORY"),
                          choiceValues: rule!CDC_RefData("CATEGORY"),
                          value: ri!complaint[recordType!CDC Complaint.fields.category],
                          saveInto: ri!complaint[recordType!CDC Complaint.fields.category],
                          required: true
                        )
                      )
                    }
                  ),
                  a!checkboxField(
                    label: "Regulatory regime",
                    labelPosition: "COLLAPSED",
                    choiceLabels: {"Payment service complaint (PSRs 2017: 15 business days)"},
                    choiceValues: {true},
                    value: if(
                      a!defaultValue(ri!complaint[recordType!CDC Complaint.fields.isPaymentService], false),
                      true,
                      null
                    ),
                    saveInto: a!save(
                      ri!complaint[recordType!CDC Complaint.fields.isPaymentService],
                      not(a!isNullOrEmpty(save!value))
                    )
                  ),
                  a!paragraphField(
                    label: "What the customer told us",
                    value: ri!complaint[recordType!CDC Complaint.fields.description],
                    saveInto: ri!complaint[recordType!CDC Complaint.fields.description],
                    height: "MEDIUM",
                    characterLimit: 255,
                    required: true
                  )
                }
              ),
              a!sectionLayout(
                label: "Triage",
                contents: {
                  a!sideBySideLayout(
                    items: {
                      a!sideBySideItem(
                        item: a!radioButtonField(
                          label: "Harm level",
                          choiceLabels: rule!CDC_RefData("HARM"),
                          choiceValues: rule!CDC_RefData("HARM"),
                          choiceLayout: "COMPACT",
                          value: ri!complaint[recordType!CDC Complaint.fields.harmLevel],
                          saveInto: ri!complaint[recordType!CDC Complaint.fields.harmLevel],
                          required: true
                        )
                      ),
                      a!sideBySideItem(
                        item: a!dropdownField(
                          label: "Consumer Duty outcome",
                          placeholder: "Select an outcome",
                          choiceLabels: rule!CDC_RefData("CD_OUTCOME"),
                          choiceValues: rule!CDC_RefData("CD_OUTCOME"),
                          value: ri!complaint[recordType!CDC Complaint.fields.consumerDutyOutcome],
                          saveInto: ri!complaint[recordType!CDC Complaint.fields.consumerDutyOutcome],
                          required: true
                        )
                      )
                    }
                  )
                }
              )
            }
          ),
          /* ---------------- Right: live assistance ---------------- */
          a!columnLayout(
            width: "MEDIUM",
            contents: {
              a!cardLayout(
                style: "INFO",
                marginBelow: "STANDARD",
                contents: {
                  a!richTextDisplayField(
                    labelPosition: "COLLAPSED",
                    value: {
                      a!richTextIcon(icon: "clock-o"),
                      a!richTextItem(text: "  Regulatory deadlines", style: "STRONG", size: "MEDIUM")
                    }
                  ),
                  a!richTextDisplayField(
                    labelPosition: "COLLAPSED",
                    showWhen: isnull(local!deadlines.summaryResolutionDue),
                    value: a!richTextItem(text: "Enter the received date to calculate deadlines.", color: "SECONDARY")
                  ),
                  a!richTextDisplayField(
                    label: "Summary resolution by (3 business days)",
                    showWhen: not(isnull(local!deadlines.summaryResolutionDue)),
                    value: a!richTextItem(text: text(local!deadlines.summaryResolutionDue, "ddd dd mmm yyyy"), style: "STRONG")
                  ),
                  a!richTextDisplayField(
                    label: "Final response by",
                    showWhen: not(isnull(local!deadlines.finalResponseDue)),
                    value: a!richTextItem(text: text(local!deadlines.finalResponseDue, "ddd dd mmm yyyy"), style: "STRONG")
                  ),
                  a!richTextDisplayField(
                    label: "Exceptional long-stop",
                    showWhen: not(isnull(local!deadlines.exceptionalLongStop)),
                    value: text(local!deadlines.exceptionalLongStop, "ddd dd mmm yyyy")
                  ),
                  a!richTextDisplayField(
                    labelPosition: "COLLAPSED",
                    showWhen: not(isnull(local!deadlines.ruleApplied)),
                    value: a!richTextItem(text: local!deadlines.ruleApplied, color: "SECONDARY", size: "SMALL")
                  )
                }
              ),
              a!cardLayout(
                style: "ACCENT",
                showWhen: not(a!isNullOrEmpty(ri!complaint[recordType!CDC Complaint.fields.description])),
                contents: {
                  a!richTextDisplayField(
                    labelPosition: "COLLAPSED",
                    value: {
                      a!richTextIcon(icon: "magic"),
                      a!richTextItem(text: "  Suggested triage", style: "STRONG", size: "MEDIUM"),
                      char(10),
                      "Harm: ",
                      a!richTextItem(text: local!triage.harmLevel, style: "STRONG"),
                      char(10),
                      "Outcome: ",
                      a!richTextItem(text: local!triage.consumerDutyOutcome, style: "STRONG")
                    }
                  ),
                  a!richTextDisplayField(
                    labelPosition: "COLLAPSED",
                    value: a!richTextBulletedList(items: local!triage.reasons),
                    showWhen: length(local!triage.reasons) > 0
                  ),
                  a!buttonArrayLayout(
                    align: "START",
                    buttons: a!buttonWidget(
                      label: "Apply suggestion",
                      icon: "check",
                      style: "OUTLINE",
                      size: "SMALL",
                      saveInto: {
                        a!save(ri!complaint[recordType!CDC Complaint.fields.harmLevel], local!triage.harmLevel),
                        a!save(ri!complaint[recordType!CDC Complaint.fields.consumerDutyOutcome], local!triage.consumerDutyOutcome)
                      }
                    )
                  )
                }
              )
            }
          )
        }
      )
    },
    buttons: a!buttonLayout(
      primaryButtons: a!buttonWidget(
        label: "Log complaint",
        style: "SOLID",
        submit: true,
        validate: true,
        saveInto: {
          a!save(
            ri!complaint[recordType!CDC Complaint.fields.reference],
            "CMP-" & datetext(now(), "yyMMdd-HHmmss")
          ),
          a!save(ri!complaint[recordType!CDC Complaint.fields.status], "New"),
          a!save(ri!complaint[recordType!CDC Complaint.fields.ownerUsername], loggedInUser()),
          a!save(ri!complaint[recordType!CDC Complaint.fields.summaryResolutionDueOn], local!deadlines.summaryResolutionDue),
          a!save(ri!complaint[recordType!CDC Complaint.fields.finalResponseDueOn], local!deadlines.finalResponseDue),
          a!save(ri!complaint[recordType!CDC Complaint.fields.createdOn], now())
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
