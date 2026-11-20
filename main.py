import csv
import sqlite3
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from scrapers import fuel_prices, uk_hpi


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"
DATABASE_PATH = OUTPUT_DIR / "public_data.db"
DATASETS = {
    "weekly_fuel_prices": {
        "get_data": fuel_prices.get_data,
        "clean_data": fuel_prices.clean_data,
        "csv_name": "weekly_fuel_prices.csv",
        "csv_columns": {
            "date": "Date",
            "fuel": "Fuel",
            "price_at_pump_p_per_litre": "Price at pump (p/litre)",
            "pre_tax_cost_p_per_litre": "Pre-tax cost (p/litre)",
            "duty_tax_p_per_litre": "Duty tax (p/litre)",
            "vat_rate_percent": "VAT rate (%)",
            "diff_prev_week_p_per_litre": "Diff on prev week (p/litre)",
            "diff_prev_year_p_per_litre": "Diff on prev year (p/litre)",
        },
        "order_by": ("date", "fuel"),
    },
    "uk_hpi": {
        "get_data": uk_hpi.get_data,
        "clean_data": uk_hpi.clean_data,
        "csv_name": "uk_hpi.csv",
        "csv_columns": None,
        "order_by": (),
    },
}


def load_dataframe_to_sqlite(dataframe: pd.DataFrame, table_name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        dataframe.to_sql(table_name, connection, if_exists="replace", index=False)


def export_sqlite_table_to_csv(
    table_name: str,
    csv_path: Path,
    column_aliases: Optional[Dict[str, str]] = None,
    order_by: tuple[str, ...] = (),
) -> Path:
    if not table_name.replace("_", "").isalnum():
        raise ValueError(f"Invalid SQLite table name: {table_name}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        order_clause = ""
        if order_by:
            if not all(column.replace("_", "").isalnum() for column in order_by):
                raise ValueError(f"Invalid order-by column for {table_name}: {order_by}")
            order_clause = " ORDER BY " + ", ".join(f'"{column}"' for column in order_by)
        cursor = connection.execute(f'SELECT * FROM "{table_name}"{order_clause}')
        columns = [column[0] for column in cursor.description]
        if column_aliases:
            missing_columns = set(column_aliases) - set(columns)
            if missing_columns:
                raise ValueError(
                    f"Missing export columns in {table_name}: {sorted(missing_columns)}"
                )
            header = [column_aliases.get(column, column) for column in columns]
        else:
            header = columns

        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(header)
            writer.writerows(cursor)

    return csv_path


def run_pipeline() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for table_name, dataset in DATASETS.items():
        raw_dataframe = dataset["get_data"]()
        cleaned_dataframe = dataset["clean_data"](raw_dataframe)
        load_dataframe_to_sqlite(cleaned_dataframe, table_name)
        csv_path = OUTPUT_DIR / dataset["csv_name"]
        export_sqlite_table_to_csv(
            table_name,
            csv_path,
            dataset["csv_columns"],
            dataset["order_by"],
        )
        print(
            f"Loaded and exported {len(cleaned_dataframe)} rows for "
            f"{table_name}: {csv_path}"
        )

    print(f"SQLite database: {DATABASE_PATH}")


if __name__ == "__main__":
    run_pipeline()
