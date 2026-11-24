/*
  CDC_ComplianceDashboard
  Type: Interface (site page "Dashboard")   |   Rule inputs: none

  The "Consumer Duty MI" view: deadline risk, outcomes for customers,
  root causes, vulnerability. All numbers come live from the record data.
*/
a!localVariables(
  local!open: rule!CDC_RefData("OPEN_STATUS"),
  local!today: today(),

  local!openFilter: a!queryFilter(
    field: recordType!CDC Complaint.fields.status,
    operator: "in",
    value: local!open
  ),

  local!countOpen: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    filters: local!openFilter,
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!countBreached: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    filters: {
      local!openFilter,
      a!queryFilter(field: recordType!CDC Complaint.fields.finalResponseDueOn, operator: "<", value: local!today)
    },
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!countDueSoon: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    filters: {
      local!openFilter,
      a!queryFilter(field: recordType!CDC Complaint.fields.finalResponseDueOn, operator: ">=", value: local!today),
      a!queryFilter(field: recordType!CDC Complaint.fields.finalResponseDueOn, operator: "<=", value: local!today + 7)
    },
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!countVulnerableOpen: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    filters: {
      local!openFilter,
      a!queryFilter(
        field: recordType!CDC Complaint.relationships.customer.fields.isVulnerable,
        operator: "=",
        value: true
      )
    },
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!countDecided: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    filters: a!queryFilter(field: recordType!CDC Complaint.fields.decision, operator: "not null"),
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!countUpheld: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    filters: a!queryFilter(
      field: recordType!CDC Complaint.fields.decision,
      operator: "in",
      value: {"Upheld", "Partially upheld"}
    ),
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!countSummary: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    filters: a!queryFilter(field: recordType!CDC Complaint.fields.status, operator: "=", value: "Summary resolution"),
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!countAll: a!queryRecordType(
    recordType: recordType!CDC Complaint,
    fields: recordType!CDC Complaint.fields.id,
    pagingInfo: a!pagingInfo(1, 1),
    fetchTotalCount: true
  ).totalCount,

  local!redressTotal: a!defaultValue(
    index(
      a!queryRecordType(
        recordType: recordType!CDC Complaint,
        fields: a!aggregationFields(
          measures: a!measure(
            function: "SUM",
            field: recordType!CDC Complaint.fields.redressAmount,
            alias: "total"
          )
        ),
        pagingInfo: a!pagingInfo(1, 1)
      ).data.total,
      1,
      0
    ),
    0
  ),

  local!pct: if(local!countDecided = 0, 0, round(100 * local!countUpheld / local!countDecided, 0)),
  local!srcPct: if(local!countAll = 0, 0, round(100 * local!countSummary / local!countAll, 0)),

  local!kpis: {
    a!map(label: "Open complaints", value: local!countOpen, color: "#2B4C7E", icon: "inbox"),
    a!map(label: "Deadline breached", value: local!countBreached, color: "#C62828", icon: "exclamation-circle"),
    a!map(label: "Due in next 7 days", value: local!countDueSoon, color: "#B25E09", icon: "clock-o"),
    a!map(label: "Open: vulnerable customers", value: local!countVulnerableOpen, color: "#5B3F8C", icon: "heart"),
    a!map(label: "Uphold rate", value: local!pct & "%", color: "#2B4C7E", icon: "balance-scale"),
    a!map(label: "Resolved in 3 business days", value: local!srcPct & "%", color: "#1E7B3A", icon: "bolt"),
    a!map(label: "Redress paid", value: "£" & fixed(local!redressTotal, 0), color: "#1E7B3A", icon: "gbp")
  },

  {
    a!richTextDisplayField(
      labelPosition: "COLLAPSED",
      value: {
        a!richTextItem(text: "Consumer Duty complaints MI", size: "LARGE", style: "STRONG"),
        char(10),
        a!richTextItem(
          text: "Live view of DISP deadline risk, customer outcomes and root causes · " & text(local!today, "dddd dd mmmm yyyy"),
          color: "SECONDARY"
        )
      }
    ),

    /* ---------- KPI tiles ---------- */
    a!columnsLayout(
      stackWhen: {"PHONE", "TABLET_PORTRAIT"},
      marginBelow: "STANDARD",
      columns: a!forEach(
        items: local!kpis,
        expression: a!columnLayout(
          contents: a!cardLayout(
            showBorder: true,
            decorativeBarPosition: "TOP",
            decorativeBarColor: fv!item.color,
            contents: a!richTextDisplayField(
              labelPosition: "COLLAPSED",
              align: "CENTER",
              value: {
                a!richTextIcon(icon: fv!item.icon, color: fv!item.color),
                char(10),
                a!richTextItem(text: fv!item.value, size: "LARGE", style: "STRONG", color: fv!item.color),
                char(10),
                a!richTextItem(text: fv!item.label, color: "SECONDARY", size: "SMALL")
              }
            )
          )
        )
      )
    ),

    /* ---------- Charts ---------- */
    a!columnsLayout(
      stackWhen: {"PHONE", "TABLET_PORTRAIT"},
      columns: {
        a!columnLayout(
          contents: a!columnChartField(
            label: "Complaints by Consumer Duty outcome and harm",
            data: recordType!CDC Complaint,
            config: a!columnChartConfig(
              primaryGrouping: a!grouping(
                field: recordType!CDC Complaint.fields.consumerDutyOutcome,
                alias: "outcome"
              ),
              secondaryGrouping: a!grouping(
                field: recordType!CDC Complaint.fields.harmLevel,
                alias: "harm"
              ),
              measures: a!measure(
                function: "COUNT",
                field: recordType!CDC Complaint.fields.id,
                alias: "count",
                label: "Complaints"
              ),
              dataLimit: 100
            ),
            stacking: "NORMAL",
            showLegend: true,
            height: "MEDIUM",
            colorScheme: "RAINFOREST"
          )
        ),
        a!columnLayout(
          contents: a!barChartField(
            label: "Root causes (closed complaints)",
            data: a!recordData(
              recordType: recordType!CDC Complaint,
              filters: a!queryFilter(field: recordType!CDC Complaint.fields.rootCause, operator: "not null")
            ),
            config: a!barChartConfig(
              primaryGrouping: a!grouping(
                field: recordType!CDC Complaint.fields.rootCause,
                alias: "rootCause"
              ),
              measures: a!measure(
                function: "COUNT",
                field: recordType!CDC Complaint.fields.id,
                alias: "count",
                label: "Complaints"
              ),
              sort: a!sortInfo(field: "count", ascending: false),
              dataLimit: 100
            ),
            height: "MEDIUM",
            colorScheme: "MIDNIGHT"
          )
        ),
        a!columnLayout(
          contents: a!pieChartField(
            label: "Complaints by product",
            data: recordType!CDC Complaint,
            config: a!pieChartConfig(
              primaryGrouping: a!grouping(field: recordType!CDC Complaint.fields.product, alias: "product"),
              measures: a!measure(function: "COUNT", field: recordType!CDC Complaint.fields.id, alias: "count")
            ),
            style: "DONUT",
            seriesLabelStyle: "LEGEND",
            height: "MEDIUM",
            colorScheme: "OCEAN"
          )
        )
      }
    ),

    /* ---------- Work queue ---------- */
    a!sectionLayout(
      label: "Open complaints, closest deadline first",
      contents: a!gridField(
        labelPosition: "COLLAPSED",
        emptyGridMessage: "No open complaints",
        data: a!recordData(recordType: recordType!CDC Complaint, filters: local!openFilter),
        initialSorts: a!sortInfo(field: recordType!CDC Complaint.fields.finalResponseDueOn, ascending: true),
        pageSize: 10,
        showSearchBox: true,
        columns: {
          a!gridColumn(
            label: "Reference",
            sortField: recordType!CDC Complaint.fields.reference,
            value: a!linkField(
              links: a!recordLink(
                label: fv!row[recordType!CDC Complaint.fields.reference],
                recordType: recordType!CDC Complaint,
                identifier: fv!identifier
              )
            ),
            width: "NARROW_PLUS"
          ),
          a!gridColumn(
            label: "Customer",
            value: a!richTextDisplayField(
              value: {
                fv!row[recordType!CDC Complaint.relationships.customer.fields.fullName],
                if(
                  a!defaultValue(fv!row[recordType!CDC Complaint.relationships.customer.fields.isVulnerable], false),
                  {" ", a!richTextIcon(icon: "exclamation-triangle", color: "#C62828", caption: "Vulnerable customer")},
                  {}
                )
              }
            )
          ),
          a!gridColumn(
            label: "Product",
            sortField: recordType!CDC Complaint.fields.product,
            value: fv!row[recordType!CDC Complaint.fields.product]
          ),
          a!gridColumn(
            label: "Category",
            sortField: recordType!CDC Complaint.fields.category,
            value: fv!row[recordType!CDC Complaint.fields.category]
          ),
          a!gridColumn(
            label: "Harm",
            sortField: recordType!CDC Complaint.fields.harmLevel,
            value: a!tagField(
              labelPosition: "COLLAPSED",
              size: "SMALL",
              tags: a!tagItem(
                text: fv!row[recordType!CDC Complaint.fields.harmLevel],
                backgroundColor: a!match(
                  value: fv!row[recordType!CDC Complaint.fields.harmLevel],
                  equals: "High", then: "#C62828",
                  equals: "Medium", then: "#B25E09",
                  default: "#1E7B3A"
                )
              )
            ),
            width: "NARROW"
          ),
          a!gridColumn(
            label: "Status",
            sortField: recordType!CDC Complaint.fields.status,
            value: fv!row[recordType!CDC Complaint.fields.status]
          ),
          a!gridColumn(
            label: "Final response due",
            sortField: recordType!CDC Complaint.fields.finalResponseDueOn,
            value: text(fv!row[recordType!CDC Complaint.fields.finalResponseDueOn], "dd mmm yyyy")
          ),
          a!gridColumn(
            label: "Deadline",
            value: a!localVariables(
              local!s: rule!CDC_SlaStatus(
                dueDate: fv!row[recordType!CDC Complaint.fields.finalResponseDueOn],
                completedOn: null
              ),
              a!tagField(
                labelPosition: "COLLAPSED",
                size: "SMALL",
                tags: a!tagItem(text: local!s.label, backgroundColor: local!s.color, tooltip: local!s.detail)
              )
            ),
            width: "NARROW_PLUS"
          )
        }
      )
    )
  }
)
