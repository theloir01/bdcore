/*
  CDC_SuggestTriage
  Type: Expression rule   |   Returns: Map
  Rule inputs:
    category      (Text)
    description   (Text)
    isVulnerable  (Boolean)  - from the customer record

  Rule-based triage: suggests a harm level and Consumer Duty outcome, and
  explains why. Deliberately transparent (an auditor can read it). In the
  demo, position this as the place an AI skill / LLM classifier would plug in,
  with the reasons shown to the handler (human in the loop).
*/
a!localVariables(
  local!text: lower(a!defaultValue(ri!description, "")),
  local!category: a!defaultValue(ri!category, ""),
  local!vulnerable: a!defaultValue(ri!isVulnerable, false),

  local!fraudWords: {"scam", "fraud", "cloned", "unauthorised", "push payment", "impersonat"},
  local!vulnWords: {
    "bereave", "passed away", "death", "late father", "late mother", "hospital",
    "cancer", "mental health", "redundan", "lost my job", "lost job", "divorce", "carer"
  },
  local!priceWords: {"fee", "charge", "interest", "premium", "renewal", "rate", "price"},
  local!understandWords: {"unclear", "not explained", "confus", "misled", "not told", "small print", "terms"},
  local!productWords: {"mis-sold", "missold", "unsuitable", "not suitable", "affordab", "already had"},
  local!lossWords: {"£", "€", "lost", "refund", "repay", "debt", "default"},

  local!hasFraud: or(a!forEach(local!fraudWords, search(fv!item, local!text) > 0)),
  local!hasVuln: or(a!forEach(local!vulnWords, search(fv!item, local!text) > 0)),
  local!hasPrice: or(a!forEach(local!priceWords, search(fv!item, local!text) > 0)),
  local!hasUnderstand: or(a!forEach(local!understandWords, search(fv!item, local!text) > 0)),
  local!hasProduct: or(a!forEach(local!productWords, search(fv!item, local!text) > 0)),
  local!hasLoss: or(a!forEach(local!lossWords, search(fv!item, local!text) > 0)),

  local!harm: if(
    or(
      local!hasFraud,
      local!vulnerable,
      local!hasVuln,
      local!category = "Arrears handling",
      local!category = "Fraud and scams"
    ),
    "High",
    if(or(local!hasLoss, local!hasPrice, local!hasProduct), "Medium", "Low")
  ),

  local!outcome: if(
    or(local!hasFraud, local!hasVuln, local!vulnerable,
       local!category = "Arrears handling", local!category = "Claims handling"),
    "Consumer support",
    if(
      or(local!hasProduct, local!category = "Mis-selling"),
      "Products and services",
      if(
        or(local!hasUnderstand, local!category = "Communication"),
        "Consumer understanding",
        if(
          or(local!hasPrice, local!category = "Fees and charges"),
          "Price and value",
          "Consumer support"
        )
      )
    )
  ),

  a!map(
    harmLevel: local!harm,
    consumerDutyOutcome: local!outcome,
    possibleVulnerability: and(local!hasVuln, not(local!vulnerable)),
    reasons: reject(
      fn!isnull,
      {
        if(local!hasFraud, "Mentions fraud or scam indicators", null),
        if(local!vulnerable, "Customer is flagged as vulnerable", null),
        if(and(local!hasVuln, not(local!vulnerable)),
           "Wording suggests a possible vulnerability. Check and record it (FG21/1)", null),
        if(local!hasLoss, "Mentions financial loss or a refund", null),
        if(local!hasPrice, "Relates to fees, charges, rates or premiums", null),
        if(local!hasUnderstand, "Suggests information was unclear or not explained", null),
        if(local!hasProduct, "Suggests the product may not have been suitable", null)
      }
    )
  )
)
