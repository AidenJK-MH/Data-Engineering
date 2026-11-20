import unittest

import pandas as pd

from scrapers import ons_cpi


class CleanDataTests(unittest.TestCase):
    def test_keeps_selected_indices_and_drops_release_metadata_and_null_values(self) -> None:
        selected_codes = list(ons_cpi.SELECTED_SERIES_CODES)
        columns = ["Title"] + [
            "CPI: All items 2015=100" if code == "D7BT" else code
            for code in selected_codes
        ] + ["CPI annual rate"]
        row_values = {
            "2026 JAN": {"D7BT": "101.2", "L522": "110.5", "D7G7": "3.1"},
            "2026 FEB": {"D7BT": "102.4", "L522": "111.0", "D7G7": "3.2"},
            "2026 MAR": {"D7BT": None, "L522": "111.5", "D7G7": "3.3"},
        }
        raw_data = [
            ["CDID"] + selected_codes + ["D7G7"],
            ["PreUnit"] + [None] * (len(selected_codes) + 1),
            ["Unit"] + ["Index"] * len(selected_codes) + ["%"],
            ["Release Date"] + ["18-11-2026"] * (len(selected_codes) + 1),
            ["Next release"] + ["16 December 2026"] * (len(selected_codes) + 1),
            ["Important Notes"] + [None] * (len(selected_codes) + 1),
        ]
        for period, values in row_values.items():
            raw_data.append(
                [period]
                + [values.get(code) for code in selected_codes]
                + [values["D7G7"]]
            )
        raw_dataframe = pd.DataFrame(raw_data, columns=columns)

        result = ons_cpi.clean_data(raw_dataframe)

        self.assertEqual(
            list(result.columns),
            ["series_code", "series_title", "pre_unit", "unit", "period", "value"],
        )
        self.assertEqual(len(result), 5)
        self.assertEqual(set(result["series_code"]), {"D7BT", "L522"})
        self.assertNotIn("release_date", result.columns)
        self.assertNotIn("next_release", result.columns)
        first_observation = result.iloc[0]
        self.assertEqual(first_observation["series_code"], "D7BT")
        self.assertEqual(first_observation["series_title"], "CPI: All items 2015=100")
        self.assertEqual(first_observation["period"], "2026 JAN")
        self.assertEqual(first_observation["value"], 101.2)
        self.assertEqual(result.iloc[1]["unit"], "Index")
        self.assertEqual(result.iloc[1]["period"], "2026 JAN")
        self.assertEqual(result.iloc[1]["value"], 110.5)
        self.assertEqual(result.iloc[-1]["period"], "2026 MAR")
        self.assertEqual(result.iloc[-1]["value"], 111.5)

    def test_rejects_unexpected_metadata_layout(self) -> None:
        raw_dataframe = pd.DataFrame(
            [["Wrong"], ["PreUnit"], ["Unit"], ["Release Date"],
             ["Next release"], ["Important Notes"], ["2026 JAN"]],
            columns=["Title"],
        )
        with self.assertRaisesRegex(ValueError, "Unexpected ONS CPI metadata rows"):
            ons_cpi.clean_data(raw_dataframe)


if __name__ == "__main__":
    unittest.main()
