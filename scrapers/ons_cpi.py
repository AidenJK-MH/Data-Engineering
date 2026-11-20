import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

import pandas as pd


SOURCE_PAGE = (
    "https://www.ons.gov.uk/economy/inflationandpriceindices/"
    "datasets/consumerpriceindices"
)
DOWNLOAD_FILE_NAME = "mm23.csv"
EXPECTED_DOWNLOAD_HOST = "www.ons.gov.uk"
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "input" / "ons_raw"
USER_AGENT = "Mozilla/5.0 (compatible; UKPublicDataPipeline/1.0)"
ONS_METADATA_ROWS = {
    "series_code": "CDID",
    "pre_unit": "PreUnit",
    "unit": "Unit",
    "release_date": "Release Date",
    "next_release": "Next release",
    "important_notes": "Important Notes",
}
SELECTED_SERIES_CODES = (
    "D7BT",  # CPI: All items
    "D7BU",  # CPI: Food and non-alcoholic beverages
    "D7BV",  # CPI: Alcoholic beverages, tobacco and narcotics
    "D7BW",  # CPI: Clothing and footwear
    "D7BX",  # CPI: Housing, water and fuels
    "D7BY",  # CPI: Furnishings and household equipment
    "D7BZ",  # CPI: Health
    "D7C2",  # CPI: Transport
    "D7C3",  # CPI: Communication
    "D7C4",  # CPI: Recreation and culture
    "D7C5",  # CPI: Education
    "D7C6",  # CPI: Restaurants and hotels
    "D7C7",  # CPI: Miscellaneous goods and services
    "L522",  # CPIH: All items
    "CHAW",  # RPI: All items
    "CHMK",  # RPIX: All items excluding mortgage interest
    "CBZW",  # RPIY: All items excluding mortgage interest and indirect taxes
    "EAC7",  # CPI-CT: All items
    "CRQO",  # CPIH excluding owner occupiers' housing costs
    "CRQP",  # CPIH excluding owner occupiers' housing costs and council tax
)


class CsvDownloadLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.download_urls: List[str] = []
        self._href: Optional[str] = None
        self._download_name: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        if tag == "a":
            attributes = dict(attrs)
            self._href = attributes.get("href")
            self._download_name = attributes.get("data-gtm-download-file")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            link_text = " ".join("".join(self._text).split())
            if (
                self._download_name == DOWNLOAD_FILE_NAME
                or link_text == "Download Consumer price inflation time series in csv format"
            ):
                self.download_urls.append(urljoin(SOURCE_PAGE, self._href))
            self._href = None
            self._download_name = None
            self._text = []


def find_download_url() -> str:
    page_request = Request(SOURCE_PAGE, headers={"User-Agent": USER_AGENT})
    with urlopen(page_request, timeout=30) as response:
        page_html = response.read().decode("utf-8")

    parser = CsvDownloadLinkParser()
    parser.feed(page_html)
    if not parser.download_urls:
        raise RuntimeError(
            f"Could not find the {DOWNLOAD_FILE_NAME} CSV download on {SOURCE_PAGE}"
        )

    download_url = parser.download_urls[0]
    parsed_url = urlparse(download_url)
    file_uri = parse_qs(parsed_url.query).get("uri", [""])[0]
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != EXPECTED_DOWNLOAD_HOST
        or parsed_url.path != "/file"
        or not file_uri.endswith("/" + DOWNLOAD_FILE_NAME)
    ):
        raise RuntimeError(f"Unexpected ONS CSV download URL: {download_url}")

    return download_url


def get_data() -> pd.DataFrame:
    download_url = find_download_url()
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    download_path = RAW_DATA_DIR / DOWNLOAD_FILE_NAME

    download_request = Request(download_url, headers={"User-Agent": USER_AGENT})
    with urlopen(download_request, timeout=120) as response:
        download_path.write_bytes(response.read())

    metadata = {
        "source_url": download_url,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with download_path.with_suffix(".json").open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2)
        file.write("\n")

    return pd.read_csv(download_path, header=0, low_memory=False)


def clean_data(raw_dataframe: pd.DataFrame) -> pd.DataFrame:
    metadata_rows = raw_dataframe.iloc[: len(ONS_METADATA_ROWS), 0].tolist()
    if metadata_rows != list(ONS_METADATA_ROWS.values()):
        raise ValueError(
            "Unexpected ONS CPI metadata rows: "
            f"expected {list(ONS_METADATA_ROWS.values())}, found {metadata_rows}"
        )

    source_series_codes = raw_dataframe.iloc[0, 1:].astype(str)
    missing_series_codes = set(SELECTED_SERIES_CODES) - set(source_series_codes)
    if missing_series_codes:
        raise ValueError(
            f"Selected ONS CPI series codes are missing: {sorted(missing_series_codes)}"
        )

    selected_positions = [
        position
        for position, code in enumerate(source_series_codes)
        if code in SELECTED_SERIES_CODES
    ]
    metadata = pd.DataFrame(
        {
            "series_position": selected_positions,
            "series_title": raw_dataframe.columns[1:][selected_positions],
            **{
                output_name: raw_dataframe.iloc[row_position, 1:].iloc[
                    selected_positions
                ].to_numpy()
                for row_position, output_name in enumerate(ONS_METADATA_ROWS)
            },
        }
    )

    values = raw_dataframe.iloc[len(ONS_METADATA_ROWS) :, 1:].iloc[
        :, selected_positions
    ].copy()
    values.columns = selected_positions
    values.index = raw_dataframe.iloc[len(ONS_METADATA_ROWS) :, 0].astype(str)
    values = values.apply(pd.to_numeric, errors="coerce")

    long_values = (
        values.stack()
        .rename("value")
        .rename_axis(index=["period", "series_position"])
        .reset_index()
    )
    long_dataframe = long_values.merge(
        metadata,
        on="series_position",
        how="left",
        validate="many_to_one",
    )

    return long_dataframe[
        [
            "series_code",
            "series_title",
            "pre_unit",
            "unit",
            "period",
            "value",
        ]
    ]
