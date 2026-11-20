import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from scrapers import uk_hpi


class FindLatestDownloadUrlTests(unittest.TestCase):
    def test_selects_june_report_when_date_is_in_june(self) -> None:
        collection_url = uk_hpi.COLLECTION_URL_TEMPLATE.format(year=2026)
        collection_html = """
            <a href="/government/statistical-data-sets/uk-house-price-index-data-downloads-september-2026">
            UK House Price Index: data downloads September 2026</a>
            <a href="/government/statistical-data-sets/uk-house-price-index-data-downloads-june-2026">
            UK House Price Index: data downloads June 2026</a>
        """
        report_url = (
            "https://www.gov.uk/government/statistical-data-sets/"
            "uk-house-price-index-data-downloads-june-2026"
        )
        report_html = (
            '<a rel="external" href="https://publicdata.landregistry.gov.uk/'
            'market-trend-data/house-price-index-data/UK-HPI-full-file-2026-06.csv">'
            "UK HPI full file</a>"
        )

        def fake_fetch_page(url: str):
            if url == collection_url:
                return collection_html
            if url == report_url:
                return report_html
            self.fail(f"Unexpected page requested: {url}")

        with patch.object(uk_hpi, "fetch_page", side_effect=fake_fetch_page):
            download_url = uk_hpi.find_latest_download_url(date(2026, 6, 30))

        self.assertIn("UK-HPI-full-file-2026-06.csv", download_url)

    def test_falls_back_to_previous_year_when_current_year_has_no_reports(self) -> None:
        collection_2027 = uk_hpi.COLLECTION_URL_TEMPLATE.format(year=2027)
        collection_2026 = uk_hpi.COLLECTION_URL_TEMPLATE.format(year=2026)
        collection_html_2026 = """
            <a href="/government/statistical-data-sets/uk-house-price-index-data-downloads-september-2026">
            UK House Price Index: data downloads September 2026</a>
        """
        report_url = (
            "https://www.gov.uk/government/statistical-data-sets/"
            "uk-house-price-index-data-downloads-september-2026"
        )
        report_html = (
            '<a href="https://publicdata.landregistry.gov.uk/'
            'market-trend-data/house-price-index-data/UK-HPI-full-file-2026-09.csv">'
            "UK HPI full file</a>"
        )

        def fake_fetch_page(url: str):
            if url == collection_2027:
                return "<html><body>No published reports yet</body></html>"
            if url == collection_2026:
                return collection_html_2026
            if url == report_url:
                return report_html
            self.fail(f"Unexpected page requested: {url}")

        with patch.object(uk_hpi, "fetch_page", side_effect=fake_fetch_page):
            download_url = uk_hpi.find_latest_download_url(date(2027, 2, 1))

        self.assertIn("UK-HPI-full-file-2026-09.csv", download_url)


class CleanDataTests(unittest.TestCase):
    def test_standardizes_headers_converts_measures_and_preserves_date(self) -> None:
        raw_data = {column: [None] for column in uk_hpi.SOURCE_COLUMN_NAMES}
        raw_data.update(
            {
                "Date": ["01/06/2026"],
                "RegionName": ["Example Region"],
                "AreaCode": ["E00000001"],
                "AveragePrice": ["250000"],
                "Index": ["120.5"],
            }
        )

        cleaned = uk_hpi.clean_data(pd.DataFrame(raw_data))

        self.assertEqual(cleaned.loc[0, "date"], "01/06/2026")
        self.assertEqual(cleaned.loc[0, "region_name"], "Example Region")
        self.assertEqual(cleaned.loc[0, "area_code"], "E00000001")
        self.assertEqual(cleaned.loc[0, "average_price_gbp"], 250000)
        self.assertEqual(cleaned.loc[0, "hpi_index"], 120.5)
        self.assertTrue(
            pd.isna(cleaned.loc[0, "hpi_index_seasonally_adjusted"])
        )
        self.assertNotIn("AveragePrice", cleaned.columns)

    def test_raises_for_missing_expected_source_columns(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing expected UK HPI columns"):
            uk_hpi.clean_data(pd.DataFrame({"Date": ["01/06/2026"]}))


if __name__ == "__main__":
    unittest.main()
