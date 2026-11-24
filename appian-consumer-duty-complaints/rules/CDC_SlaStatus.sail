/*
  CDC_SlaStatus
  Type: Expression rule   |   Returns: Map (label, color, detail)
  Rule inputs:
    dueDate      (Date)
    completedOn  (Date)  - leave null if not yet done

  Labels: Met / Missed / Breached / Due soon / On track
  "Due soon" = 5 business days or fewer left.
*/
a!localVariables(
  local!holidays: rule!CDC_UkBankHolidays(),
  local!today: today(),
  local!green: "#1E7B3A",
  local!amber: "#B25E09",
  local!red: "#C62828",
  local!grey: "#5F6B7A",
  if(
    isnull(ri!dueDate),
    a!map(label: "No deadline", color: local!grey, detail: ""),
    if(
      not(isnull(ri!completedOn)),
      if(
        ri!completedOn <= ri!dueDate,
        a!map(label: "Met", color: local!green, detail: "Completed in time"),
        a!map(label: "Missed", color: local!red, detail: "Completed after the deadline")
      ),
      if(
        ri!dueDate < local!today,
        a!map(
          label: "Breached",
          color: local!red,
          detail: "Overdue by " & (networkdays(ri!dueDate, local!today, local!holidays) - 1) & " business days"
        ),
        a!localVariables(
          local!left: networkdays(local!today, ri!dueDate, local!holidays) - 1,
          if(
            local!left <= 5,
            a!map(label: "Due soon", color: local!amber, detail: local!left & " business days left"),
            a!map(label: "On track", color: local!green, detail: local!left & " business days left")
          )
        )
      )
    )
  )
)
