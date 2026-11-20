from pathlib import Path
from urllib.request import urlopen


DOWNLOAD_URL = (
    "https://assets.publishing.service.gov.uk/media/"
    "6afb1216ccb3ea58ac8743ac/Weekly_Fuel_Prices_16-11-26.xlsx"
)
INPUT_DIR = Path(__file__).resolve().parent / "input"


def download_latest_fuel_prices() -> Path:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = INPUT_DIR / "Weekly_Fuel_Prices_16-11-26.xlsx"

    with urlopen(DOWNLOAD_URL, timeout=60) as response:
        output_path.write_bytes(response.read())

    return output_path


if __name__ == "__main__":
    downloaded_file = download_latest_fuel_prices()
    print(f"Downloaded weekly fuel prices to: {downloaded_file}")
