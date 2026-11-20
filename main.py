import sqlite3
from pathlib import Path
from urllib.request import urlopen

from openpyxl import load_workbook
import pandas as pd


DOWNLOAD_URL = (
    "https://assets.publishing.service.gov.uk/media/"
    "6afb1216ccb3ea58ac8743ac/Weekly_Fuel_Prices_16-11-26.xlsx"
)
PROJECT_DIR = Path(__file__).resolve().parent
INPUT_DIR = PROJECT_DIR / "input"
OUTPUT_DIR = PROJECT_DIR / "output"
DATABASE_PATH = OUTPUT_DIR / "weekly_fuel_prices.db"
TABLE_NAME = "weekly_fuel_prices"
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


def download_latest_fuel_prices() -> Path:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = INPUT_DIR / "Weekly_Fuel_Prices_16-11-26.xlsx"

    with urlopen(DOWNLOAD_URL, timeout=60) as response:
        output_path.write_bytes(response.read())

    return output_path


def extract_data_to_dataframe(workbook_path: Path) -> pd.DataFrame:
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        worksheet = workbook["Data"]
        header_row = None
        date_column = None

        for row_number, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
            for column_number, value in enumerate(row):
                if value == "Date":
                    header_row = row_number
                    date_column = column_number
                    break
            if header_row is not None:
                break

        if header_row is None or date_column is None:
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


def transform_to_tall_dataframe(raw_dataframe: pd.DataFrame) -> pd.DataFrame:
    raw_dataframe = raw_dataframe.loc[raw_dataframe["Date"].notna()].copy()
    tall_dataframes = []

    for fuel, columns in SOURCE_FUEL_COLUMNS.items():
        fuel_dataframe = raw_dataframe[
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


def load_dataframe_to_sqlite(dataframe: pd.DataFrame) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                date TEXT NOT NULL,
                fuel TEXT NOT NULL CHECK (fuel IN ('Petrol', 'Diesel')),
                price_at_pump_p_per_litre REAL,
                pre_tax_cost_p_per_litre REAL,
                duty_tax_p_per_litre REAL,
                vat_rate_percent REAL,
                diff_prev_week_p_per_litre REAL,
                diff_prev_year_p_per_litre REAL,
                PRIMARY KEY (date, fuel)
            )
            """
        )
        connection.execute(f"DELETE FROM {TABLE_NAME}")
        dataframe.to_sql(TABLE_NAME, connection, if_exists="append", index=False)

    return DATABASE_PATH


if __name__ == "__main__":
    downloaded_file = download_latest_fuel_prices()
    print(f"Downloaded weekly fuel prices to: {downloaded_file}")
    raw_fuel_prices = extract_data_to_dataframe(downloaded_file)
    fuel_prices = transform_to_tall_dataframe(raw_fuel_prices)
    database_file = load_dataframe_to_sqlite(fuel_prices)
    print(f"Loaded {len(fuel_prices)} records into {TABLE_NAME} in: {database_file}")
