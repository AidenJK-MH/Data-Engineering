# UK Public Data Pipeline

A small Python data pipeline that downloads three public UK datasets, transforms
them with pandas, loads them into SQLite, and exports CSV files from SQLite for
Power BI.

## What it does

The pipeline currently processes:

1. **Weekly road fuel prices** from the Department for Energy Security and Net
   Zero (DESNZ).
2. **UK House Price Index (UK HPI)** from HM Land Registry.
3. **Consumer price inflation time series (MM23)** from the Office for National
   Statistics (ONS).

For each dataset, the main script calls the scraper's `get_data()` function,
passes the resulting DataFrame to `clean_data()`, replaces the corresponding
SQLite table, then exports that table to CSV. SQLite is the source of truth for
the Power BI CSV exports.

## Project structure

```text
.
├── main.py
├── requirements.txt
├── scrapers/
│   ├── __init__.py
│   ├── fuel_prices.py
│   ├── ons_cpi.py
│   └── uk_hpi.py
├── tests/
│   ├── test_fuel_prices.py
│   ├── test_ons_cpi.py
│   └── test_uk_hpi.py
├── input/                         # Downloaded source files and metadata
│   ├── ons_raw/
│   └── uk_hpi_raw/
└── output/                        # Generated database and Power BI CSVs
    ├── public_data.db
    ├── weekly_fuel_prices.csv
    ├── uk_hpi.csv
    └── ons_cpi.csv
```

`input/` and `output/` are generated/local data directories and are ignored by
Git. The downloaded source files are retained locally to support inspection and
reproducibility; they are overwritten when the same download filename is used.
The ONS and HPI downloads include JSON sidecars recording the source URL and
retrieval time.

## Setup and run

Python 3.9 or later is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

The pipeline creates `output/` as needed. Each source is fetched and processed
in the order configured in `main.py`. A successful run prints the number of
records loaded and the path of each CSV.

## Dataset details and decisions

### Weekly fuel prices

`scrapers/fuel_prices.py` finds the Excel attachment labelled
**Weekly road fuel prices (Excel)** on the GOV.UK statistics page. It reads the
`Data` worksheet and locates the table by finding the `Date` header, rather than
assuming a fixed row number.

The cleaned table has one row per date and category:

- `Petrol`
- `Diesel`
- `Diff` = Diesel minus Petrol

The `Diff` row is calculated in the DataFrame before SQLite ingestion. Numeric
measures are subtracted, including pump price, pre-tax cost, duty, VAT rate,
and previous-week/year changes. Thus, for fields such as duty and VAT, `Diff`
represents a mathematical difference between fuel values, not a separate
applicable rate.

The pre-tax cost calculation is:

```text
pump price / (1 + VAT rate / 100) - duty
```

Dates are stored in SQLite as `YYYY-MM-DD`; the CSV uses a display-friendly set
of column names.

### UK House Price Index

`scrapers/uk_hpi.py` checks the GOV.UK collection for the current local year and
searches its monthly report links backwards from the current month. If there is
no suitable report, it tries earlier months and then earlier collection years,
down to 2026. The chosen report's **UK HPI full file** attachment is downloaded.

The source file is wide. Cleaning standardizes the 54 column names and converts
measure columns to numeric values, with blank/unparseable values represented as
nulls. The source `Date` remains text in `DD/MM/YYYY` format, as requested.
Missing columns required by the current mapping cause an explicit error.

### ONS consumer price inflation time series (MM23)

The ONS file is a wide matrix with series metadata in its first six rows and
periods down the remaining rows. Cleaning selects 20 series by ONS series code,
then reshapes non-null observations to a long table with:

- `series_code`
- `series_title`
- `pre_unit`
- `unit`
- `period`
- `value`

Release date, next release, and notes are retained in the raw download and its
metadata context but omitted from the analytical table. Period labels are kept
as published (for example, `1987` or `2026 OCT`) rather than parsed into a
single date type. New period rows and additional unselected source series do not
require fixed row/column counts; if a selected series code disappears, cleaning
fails with an explicit error.

The selected ONS series are declared in `SELECTED_SERIES_CODES` in
`scrapers/ons_cpi.py`. They include headline CPI, CPIH, RPI, RPIX, RPIY, CPI-CT,
two CPIH variants, and the 12 broad CPI categories. Annual-rate measures are
not selected; percentage changes can be calculated from index values in Power
BI where appropriate.

## SQLite and Power BI outputs

The shared SQLite database is:

```text
output/public_data.db
```

It contains one table per source:

| SQLite table | Power BI CSV |
|---|---|
| `weekly_fuel_prices` | `output/weekly_fuel_prices.csv` |
| `uk_hpi` | `output/uk_hpi.csv` |
| `ons_cpi` | `output/ons_cpi.csv` |

Each run replaces each table with the current cleaned source data, then exports
the CSV from that table. Connect Power BI Desktop to the CSV with **Get data →
Text/CSV**. The CSVs are generated artifacts; do not edit them directly. Update
the scraper or transform instead, then rerun the pipeline.

### Diesel–petrol price gap in Power BI

The fuel data already contains a `Diff` category. To chart its pump-price
difference, create this measure (change the table name if Power BI assigned a
different name):

```DAX
Diesel-Petrol Gap (p/litre) =
CALCULATE (
    MAX ( 'weekly_fuel_prices'[Price at pump (p/litre)] ),
    REMOVEFILTERS ( 'weekly_fuel_prices'[Fuel] ),
    'weekly_fuel_prices'[Fuel] = "Diff"
)
```

Add a line chart, place `Date` on the X-axis and the measure on the Y-axis, and
sort the date ascending. A positive value means diesel was more expensive than
petrol; a negative value means it was cheaper.

Power BI Service cannot refresh a CSV stored only on a personal computer without
additional connectivity. For scheduled service refresh, store the CSV in an
accessible OneDrive/SharePoint location or configure a gateway, and ensure the
pipeline runs before the Power BI refresh.

## Tests

Run the test suite from the project root:

```bash
python -m unittest discover -s tests -v
```

Current tests cover:

- Fuel `Diff` rows and Diesel-minus-Petrol calculations.
- HPI month lookup, year fallback, header standardization, numeric conversion,
  and required source columns.
- ONS metadata layout, selected-series filtering, long-form reshaping, and
  omission of null observations.

## Operating recommendations and known limitations

- **Schedule the pipeline:** it currently runs only when invoked. For a local
  Mac workflow, schedule it with `launchd` or cron, then refresh Power BI after
  the script succeeds.
- **Keep Power BI and pipeline outputs in sync:** Power BI Import mode uses the
  latest CSV only after its next refresh. A local CSV needs a gateway or a
  cloud-synced location for Power BI Service refresh.
- **Protect the last good database:** each table is replaced independently.
  If a later source fails, earlier tables may already have been refreshed.
  Consider adding a staging-and-transaction strategy before relying on this for
  a client-facing production refresh.
- **Review source revisions:** the pipeline downloads the current published
  source each run. HPI and ONS raw files use stable local filenames and are
  overwritten; the sidecars record the latest URL and retrieval time, not a
  complete history of source revisions.
- **Maintain the ONS selection:** review `SELECTED_SERIES_CODES` if the analysis
  scope changes or ONS retires/renames a series.
- **Interpret the dates carefully:** fuel prices are weekly, HPI is monthly,
  and ONS period values have mixed source labels. Aggregate or map periods
  deliberately when comparing these sources in a single Power BI visual.

## Dependencies

Runtime dependencies are listed in `requirements.txt`:

- `pandas` for DataFrame transformations and CSV handling.
- `openpyxl` for reading the fuel-price workbook.

SQLite and HTML parsing use Python's standard library.
