import calendar
import json
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

import pandas as pd


COLLECTION_URL_TEMPLATE = (
    "https://www.gov.uk/government/collections/"
    "uk-house-price-index-reports-{year}"
)
REPORT_LINK_TEXT_PATTERN = re.compile(
    r"^UK House Price Index: data downloads "
    r"([A-Za-z]+) (\d{4})$"
)
REPORT_PATH_PATTERN = re.compile(
    r"^/government/statistical-data-sets/"
    r"uk-house-price-index-data-downloads-([a-z]+)-(\d{4})(?:--\d+)?$"
)
MINIMUM_YEAR = 2026
FULL_FILE_LINK_TEXT = "UK HPI full file"
EXPECTED_DOWNLOAD_HOST = "publicdata.landregistry.gov.uk"
INPUT_DIR = Path(__file__).resolve().parent.parent / "input"
RAW_DATA_DIR = INPUT_DIR / "uk_hpi_raw"
SOURCE_COLUMN_NAMES = {
    "Date": "date",
    "RegionName": "region_name",
    "AreaCode": "area_code",
    "AveragePrice": "average_price_gbp",
    "Index": "hpi_index",
    "IndexSA": "hpi_index_seasonally_adjusted",
    "1m%Change": "change_1m_pct",
    "12m%Change": "change_12m_pct",
    "AveragePriceSA": "average_price_seasonally_adjusted_gbp",
    "SalesVolume": "sales_volume",
    "DetachedPrice": "detached_price_gbp",
    "DetachedIndex": "detached_index",
    "Detached1m%Change": "detached_change_1m_pct",
    "Detached12m%Change": "detached_change_12m_pct",
    "SemiDetachedPrice": "semi_detached_price_gbp",
    "SemiDetachedIndex": "semi_detached_index",
    "SemiDetached1m%Change": "semi_detached_change_1m_pct",
    "SemiDetached12m%Change": "semi_detached_change_12m_pct",
    "TerracedPrice": "terraced_price_gbp",
    "TerracedIndex": "terraced_index",
    "Terraced1m%Change": "terraced_change_1m_pct",
    "Terraced12m%Change": "terraced_change_12m_pct",
    "FlatPrice": "flat_price_gbp",
    "FlatIndex": "flat_index",
    "Flat1m%Change": "flat_change_1m_pct",
    "Flat12m%Change": "flat_change_12m_pct",
    "CashPrice": "cash_price_gbp",
    "CashIndex": "cash_index",
    "Cash1m%Change": "cash_change_1m_pct",
    "Cash12m%Change": "cash_change_12m_pct",
    "CashSalesVolume": "cash_sales_volume",
    "MortgagePrice": "mortgage_price_gbp",
    "MortgageIndex": "mortgage_index",
    "Mortgage1m%Change": "mortgage_change_1m_pct",
    "Mortgage12m%Change": "mortgage_change_12m_pct",
    "MortgageSalesVolume": "mortgage_sales_volume",
    "FTBPrice": "first_time_buyer_price_gbp",
    "FTBIndex": "first_time_buyer_index",
    "FTB1m%Change": "first_time_buyer_change_1m_pct",
    "FTB12m%Change": "first_time_buyer_change_12m_pct",
    "FOOPrice": "former_owner_occupier_price_gbp",
    "FOOIndex": "former_owner_occupier_index",
    "FOO1m%Change": "former_owner_occupier_change_1m_pct",
    "FOO12m%Change": "former_owner_occupier_change_12m_pct",
    "NewPrice": "new_build_price_gbp",
    "NewIndex": "new_build_index",
    "New1m%Change": "new_build_change_1m_pct",
    "New12m%Change": "new_build_change_12m_pct",
    "NewSalesVolume": "new_build_sales_volume",
    "OldPrice": "existing_property_price_gbp",
    "OldIndex": "existing_property_index",
    "Old1m%Change": "existing_property_change_1m_pct",
    "Old12m%Change": "existing_property_change_12m_pct",
    "OldSalesVolume": "existing_property_sales_volume",
}
NON_NUMERIC_COLUMNS = {"date", "region_name", "area_code"}


class GovUkLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[Tuple[str, str]] = []
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
            self.links.append((" ".join("".join(self._text).split()), self._href))
            self._href = None
            self._text = []


def fetch_page(url: str) -> Optional[str]:
    try:
        with urlopen(url, timeout=30) as response:
            return response.read().decode("utf-8")
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def find_latest_download_url(as_of_date: Optional[date] = None) -> str:
    as_of_date = as_of_date or date.today()
    current_year = as_of_date.year
    if current_year < MINIMUM_YEAR:
        raise RuntimeError(
            f"Cannot search UK HPI reports before {MINIMUM_YEAR}."
        )

    for year in range(current_year, MINIMUM_YEAR - 1, -1):
        collection_url = COLLECTION_URL_TEMPLATE.format(year=year)
        collection_html = fetch_page(collection_url)
        if collection_html is None:
            continue

        parser = GovUkLinkParser()
        parser.feed(collection_html)
        reports: Dict[Tuple[int, int], str] = {}
        for link_text, href in parser.links:
            match = REPORT_LINK_TEXT_PATTERN.match(link_text)
            path_match = REPORT_PATH_PATTERN.match(urlparse(href).path)
            if not match or not path_match:
                continue
            month_name, link_year = match.groups()
            path_month, path_year = path_match.groups()
            if link_year != path_year or month_name.lower() != path_month:
                continue
            try:
                month = list(calendar.month_name).index(month_name)
            except ValueError:
                continue
            if month:
                reports[(int(link_year), month)] = urljoin(collection_url, href)

        last_month = as_of_date.month if year == current_year else 12
        for month in range(last_month, 0, -1):
            report_url = reports.get((year, month))
            if report_url is None:
                continue
            report_html = fetch_page(report_url)
            if report_html is None:
                continue

            attachment_parser = GovUkLinkParser()
            attachment_parser.feed(report_html)
            for link_text, href in attachment_parser.links:
                if link_text != FULL_FILE_LINK_TEXT:
                    continue
                download_url = urljoin(report_url, href)
                parsed_url = urlparse(download_url)
                if (
                    parsed_url.scheme == "https"
                    and parsed_url.hostname == EXPECTED_DOWNLOAD_HOST
                    and parsed_url.path.lower().endswith(".csv")
                ):
                    return download_url

    raise RuntimeError(
        f"Could not find a UK HPI full-file download from {MINIMUM_YEAR} onward."
    )


def get_data() -> pd.DataFrame:
    download_url = find_latest_download_url()
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    download_path = RAW_DATA_DIR / Path(urlparse(download_url).path).name
    with urlopen(download_url, timeout=120) as response:
        download_path.write_bytes(response.read())

    metadata_path = download_path.with_suffix(".json")
    metadata = {
        "source_url": download_url,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)
        metadata_file.write("\n")

    return pd.read_csv(download_path, header=0, keep_default_na=True)


def clean_data(dataframe: pd.DataFrame) -> pd.DataFrame:
    missing_columns = set(SOURCE_COLUMN_NAMES) - set(dataframe.columns)
    if missing_columns:
        raise ValueError(f"Missing expected UK HPI columns: {sorted(missing_columns)}")

    cleaned_dataframe = dataframe.rename(columns=SOURCE_COLUMN_NAMES).copy()
    numeric_columns = [
        column
        for column in cleaned_dataframe.columns
        if column not in NON_NUMERIC_COLUMNS
    ]
    cleaned_dataframe[numeric_columns] = cleaned_dataframe[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    return cleaned_dataframe
