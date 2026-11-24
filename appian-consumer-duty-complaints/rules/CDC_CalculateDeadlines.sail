/*
  CDC_CalculateDeadlines
  Type: Expression rule   |   Returns: Map
  Rule inputs:
    receivedOn        (Date and Time)
    isPaymentService  (Boolean)

  Rules applied:
    - Summary resolution (DISP 1.5): resolve by close of business on the 3rd
      business day after the day of receipt.
    - Final response, standard (DISP 1.6.2R): 8 weeks after receipt.
    - Final response, payment services (DISP 1.6.2A): 15 business days, or up
      to 35 business days in exceptional circumstances (with a holding reply).
  Simplification: anything received on a given day counts as received that
  day (no cut-off time / non-business-day roll-forward).

  Example test: rule!CDC_CalculateDeadlines(
    receivedOn: datetime(2026, 12, 23, 10, 0, 0), isPaymentService: true)
  → summary resolution due Wed 30 Dec 2026 (24th = day 1, skips 25th,
    the weekend and the Mon 28th substitute holiday, 29th = day 2, 30th = day 3).
*/
a!localVariables(
  local!received: todate(ri!receivedOn),
  local!isPayments: a!defaultValue(ri!isPaymentService, false),
  local!holidays: rule!CDC_UkBankHolidays(),
  if(
    isnull(ri!receivedOn),
    a!map(
      summaryResolutionDue: null,
      finalResponseDue: null,
      exceptionalLongStop: null,
      ruleApplied: null
    ),
    a!map(
      summaryResolutionDue: workday(local!received, 3, local!holidays),
      finalResponseDue: if(
        local!isPayments,
        workday(local!received, 15, local!holidays),
        local!received + 56
      ),
      exceptionalLongStop: if(
        local!isPayments,
        workday(local!received, 35, local!holidays),
        null
      ),
      ruleApplied: if(
        local!isPayments,
        "DISP 1.6.2A: payment services, 15 business days (35 if exceptional)",
        "DISP 1.6.2R: final response within 8 weeks"
      )
    )
  )
)
