from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

import pandas as pd
from openpyxl import load_workbook


SOURCE_PAGE = "https://www.gov.uk/government/statistics/weekly-road-fuel-prices"
EXCEL_LINK_TEXT = "Weekly road fuel prices (Excel)"
INPUT_DIR = Path(__file__).resolve().parent.parent / "input"
SOURCE_FUEL_COLUMNS = {
    "Petrol": {
        "pump": "ULSP: Pump price (p/litre)",
        "week_diff": "ULSP: Diff on previous week (p/litre)",
        "year_diff": "ULSP: Diff on previous year (p/litre)",
        "duty": "ULSP: Duty rate (p/litre)",
        "vat": "ULSP: VAT rate (%)",
    },
    "Diesel": {
        "pump": "ULSD: Pump price (p/litre)",
        "week_diff": "ULSD: Diff on previous week (p/litre)",
        "year_diff": "ULSD: Diff on previous year (p/litre)",
        "duty": "ULSD: Duty rate (p/litre)",
        "vat": "ULSD: VAT rate (%)",
    },
}


class ExcelAttachmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attachment_urls: List[str] = []
        self._href: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            link_text = " ".join("".join(self._text).split())
            if link_text == EXCEL_LINK_TEXT:
                self.attachment_urls.append(urljoin(SOURCE_PAGE, self._href))
            self._href = None
            self._text = []


def get_data() -> pd.DataFrame:
    with urlopen(SOURCE_PAGE, timeout=30) as response:
        page_html = response.read().decode("utf-8")

    parser = ExcelAttachmentParser()
    parser.feed(page_html)
    if not parser.attachment_urls:
        raise RuntimeError(f"Could not find {EXCEL_LINK_TEXT!r} on {SOURCE_PAGE}")

    download_url = parser.attachment_urls[0]
    parsed_url = urlparse(download_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "assets.publishing.service.gov.uk"
        or not parsed_url.path.lower().endswith(".xlsx")
    ):
        raise RuntimeError(f"Unexpected Excel attachment URL: {download_url}")

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    workbook_path = INPUT_DIR / Path(parsed_url.path).name
    with urlopen(download_url, timeout=60) as response:
        workbook_path.write_bytes(response.read())

    return extract_data_to_dataframe(workbook_path)


def extract_data_to_dataframe(workbook_path: Path) -> pd.DataFrame:
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        worksheet = workbook["Data"]
        header_row = None
        for row_number, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if "Date" in row:
                header_row = row_number
                break

        if header_row is None:
            raise ValueError("Could not find a 'Date' header in the Data sheet.")

        source_headers = next(
            worksheet.iter_rows(
                min_row=header_row,
                max_row=header_row,
                values_only=True,
            )
        )
        required_headers = {
            "Date",
            *(header for columns in SOURCE_FUEL_COLUMNS.values() for header in columns.values()),
        }
        missing_headers = required_headers - set(source_headers)
        if missing_headers:
            raise ValueError(f"Missing expected headers in the Data sheet: {sorted(missing_headers)}")

        excel_rows = list(
            worksheet.iter_rows(
                min_row=header_row + 1,
                max_col=len(source_headers),
                values_only=True,
            )
        )
        return pd.DataFrame(excel_rows, columns=source_headers)
    finally:
        workbook.close()


def clean_data(raw_dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = raw_dataframe.loc[raw_dataframe["Date"].notna()].copy()
    tall_dataframes = []

    for fuel, columns in SOURCE_FUEL_COLUMNS.items():
        fuel_dataframe = dataframe[
            [
                "Date",
                columns["pump"],
                columns["duty"],
                columns["vat"],
                columns["week_diff"],
                columns["year_diff"],
            ]
        ].copy()
        fuel_dataframe.columns = [
            "date",
            "price_at_pump_p_per_litre",
            "duty_tax_p_per_litre",
            "vat_rate_percent",
            "diff_prev_week_p_per_litre",
            "diff_prev_year_p_per_litre",
        ]
        fuel_dataframe["fuel"] = fuel
        tall_dataframes.append(fuel_dataframe)

    dataframe = pd.concat(tall_dataframes, ignore_index=True)
    dataframe["date"] = pd.to_datetime(dataframe["date"]).dt.strftime("%Y-%m-%d")
    numeric_columns = [
        "price_at_pump_p_per_litre",
        "duty_tax_p_per_litre",
        "vat_rate_percent",
        "diff_prev_week_p_per_litre",
        "diff_prev_year_p_per_litre",
    ]
    dataframe[numeric_columns] = dataframe[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    dataframe["pre_tax_cost_p_per_litre"] = (
        dataframe["price_at_pump_p_per_litre"]
        / (1 + dataframe["vat_rate_percent"] / 100)
        - dataframe["duty_tax_p_per_litre"]
    ).round(6)

    return dataframe[
        [
            "date",
            "fuel",
            "price_at_pump_p_per_litre",
            "pre_tax_cost_p_per_litre",
            "duty_tax_p_per_litre",
            "vat_rate_percent",
            "diff_prev_week_p_per_litre",
            "diff_prev_year_p_per_litre",
        ]
    ]
