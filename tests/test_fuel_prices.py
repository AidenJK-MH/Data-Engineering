import unittest

import pandas as pd

from scrapers import fuel_prices


class CleanDataTests(unittest.TestCase):
    def test_adds_diesel_minus_petrol_difference_row_per_date(self) -> None:
        raw_data = {
            "Date": [pd.Timestamp("2026-01-05")],
            "ULSP: Pump price (p/litre)": [150.0],
            "ULSP: Diff on previous week (p/litre)": [1.0],
            "ULSP: Diff on previous year (p/litre)": [5.0],
            "ULSP: Duty rate (p/litre)": [50.0],
            "ULSP: VAT rate (%)": [20.0],
            "ULSD: Pump price (p/litre)": [160.0],
            "ULSD: Diff on previous week (p/litre)": [2.0],
            "ULSD: Diff on previous year (p/litre)": [8.0],
            "ULSD: Duty rate (p/litre)": [52.0],
            "ULSD: VAT rate (%)": [20.0],
        }

        result = fuel_prices.clean_data(pd.DataFrame(raw_data))
        difference = result.loc[result["fuel"] == "Diff"].iloc[0]

        self.assertEqual(len(result), 3)
        self.assertEqual(difference["date"], "2026-01-05")
        self.assertEqual(difference["price_at_pump_p_per_litre"], 10.0)
        self.assertEqual(difference["pre_tax_cost_p_per_litre"], 6.333333)
        self.assertEqual(difference["duty_tax_p_per_litre"], 2.0)
        self.assertEqual(difference["vat_rate_percent"], 0.0)
        self.assertEqual(difference["diff_prev_week_p_per_litre"], 1.0)
        self.assertEqual(difference["diff_prev_year_p_per_litre"], 3.0)


if __name__ == "__main__":
    unittest.main()
