/*
  CDC_UkBankHolidays
  Type: Expression rule   |   Rule inputs: none   |   Returns: List of Date

  England & Wales bank holidays 2025-2027 (source: gov.uk/bank-holidays).
  Used by business-day calculations for DISP deadlines.
  Scotland and Northern Ireland have extra holidays. For a UK&I build you
  would hold these as reference data per jurisdiction. Mention that in the demo.
*/
{
  /* 2025 */
  date(2025, 1, 1),
  date(2025, 4, 18),
  date(2025, 4, 21),
  date(2025, 5, 5),
  date(2025, 5, 26),
  date(2025, 8, 25),
  date(2025, 12, 25),
  date(2025, 12, 26),
  /* 2026 */
  date(2026, 1, 1),
  date(2026, 4, 3),
  date(2026, 4, 6),
  date(2026, 5, 4),
  date(2026, 5, 25),
  date(2026, 8, 31),
  date(2026, 12, 25),
  date(2026, 12, 28),
  /* 2027 */
  date(2027, 1, 1),
  date(2027, 3, 26),
  date(2027, 3, 29),
  date(2027, 5, 3),
  date(2027, 5, 31),
  date(2027, 8, 30),
  date(2027, 12, 27),
  date(2027, 12, 28)
}
