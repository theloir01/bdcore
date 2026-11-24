/*
  CDC_RefData
  Type: Expression rule   |   Returns: List of Text
  Rule inputs:
    type (Text)  e.g. "PRODUCT", "STATUS", "OPEN_STATUS"

  One place for every choice list in the app. In a production build these
  would be reference-data records so the business can maintain them.
*/
a!localVariables(
  local!lists: a!map(
    CHANNEL: {"Phone", "Email", "Web form", "Branch", "Letter", "Social media"},
    PRODUCT: {
      "Current account", "Savings", "Credit card", "Personal loan", "Mortgage",
      "Payments", "Home insurance", "Motor insurance"
    },
    /* Products whose complaints default to the PSD2 15-business-day rule */
    PAYMENT_PRODUCTS: {"Current account", "Payments"},
    CATEGORY: {
      "Fraud and scams", "Fees and charges", "Service", "Communication",
      "Mis-selling", "Payment delay", "Claims handling", "Arrears handling"
    },
    STATUS: {
      "New", "Acknowledged", "Investigating", "Summary resolution",
      "Final response issued", "Referred to FOS", "Closed"
    },
    OPEN_STATUS: {"New", "Acknowledged", "Investigating"},
    HARM: {"Low", "Medium", "High"},
    CD_OUTCOME: {
      "Products and services", "Price and value",
      "Consumer understanding", "Consumer support"
    },
    DECISION: {"Upheld", "Partially upheld", "Not upheld"},
    ROOT_CAUSE: {
      "Process", "People", "System", "Product design",
      "Communication", "Third party", "No fault found"
    },
    VULNERABILITY: {"Health", "Life event", "Resilience", "Capability"},
    SEGMENT: {"Retail", "Premier", "SME"},
    EVENT_TYPE: {
      "Complaint logged", "Acknowledgement sent", "Note", "Customer contact",
      "Status change", "Final response sent", "Referred to FOS"
    }
  ),
  index(local!lists, upper(ri!type), {})
)
