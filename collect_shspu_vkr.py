from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


SEARCH_URL = "https://irbis.shspu.ru/cgi-bin/irbis64r_plus/cgiirbis_64_ft.exe?LNG=&Z21ID=15141910151016115135435&I21DBN=VKR1_FULLTEXT&P21DBN=VKR1&S21STN=1&S21REF=10&S21FMT=briefHTML_ft&C21COM=S&S21CNR=5&S21P01=0&S21P02=0&S21LOG=1&S21P03=K=&USES21ALL=1&S21STR=%D0%9F%D0%95%D0%94%D0%90%D0%93%D0%9E%D0%93%20%D0%94%D0%9E%D0%9F%D0%9E%D0%9B%D0%9D%D0%98%D0%A2%D0%95%D0%9B%D0%AC%D0%9D%D0%9E%D0%93%D0%9E%20%D0%98%D0%9D%D0%96%D0%95%D0%9D%D0%95%D0%A0%D0%9D%D0%9E%2D%D0%A2%D0%95%D0%A5%D0%9D%D0%9E%D0%9B%D0%9E%D0%93%D0%98%D0%A7%D0%95%D0%A1%D0%9A%D0%9E%D0%93%D0%9E%20%D0%9E%D0%91%D0%A0%D0%90%D0%97%D0%9E%D0%92%D0%90%D0%9D%D0%98%D0%AF"
IMAGE_URL = "https://irbis.shspu.ru/cgi-bin/irbis64r_plus/cgiirbis_64_ft.exe?C21COM=7&I21DBN=VKR1_READER&P21DBN=VKR1&IMAGE_FILE_NAME={image_file_name}&IMAGE_FILE_MFN={mfn}&Z21ID={z21id}&FILE_PAGE={page}&S21AllTRM="


@dataclass(frozen=True)
class WorkRecord:
    mfn: int
    image_file_name: str
    z21id: str
    page_count: int
    title: str


def decode_js_string(value: str) -> str:
    return value.encode("utf-8").decode("unicode_escape").strip("|")


def clean_filename(value: str, limit: int = 90) -> str:
    value = re.sub(r"[^\w.\-]+", "_", value, flags=re.UNICODE).strip("_")
    return value[:limit] or "untitled"


def default_images_dir(output_dir: Path) -> Path:
    return output_dir / "_images"


def record_basename(record_index: int, record: WorkRecord) -> str:
    title = clean_filename(record.title)
    if title.lower().endswith(".pdf"):
        title = title[:-4]
    return f"{record_index:02d}_mfn_{record.mfn}_{title}"


def record_images_basename(record_index: int, record: WorkRecord) -> str:
    return f"{record_index:02d}_mfn_{record.mfn}_{clean_filename(record.title)}"


def parse_records(html: str) -> list[WorkRecord]:
    records: list[WorkRecord] = []
    pattern = re.compile(
        r"var currMFN = (?P<mfn>\d+);\s+srrs_VKR1_FULLTEXT\.addRecord\(\{(?P<body>.*?)\}\);",
        re.DOTALL,
    )

    for match in pattern.finditer(html):
        mfn = int(match.group("mfn"))
        body = match.group("body")
        image_match = re.search(r'"IMAGE_FILE_NAME"\s*:\s*"(?P<value>.*?)"', body)
        z21id_match = re.search(r'"Z21ID"\s*:\s*"(?P<value>.*?)"', body)
        pages_match = re.search(r'"955"\s*:\s*"(?P<value>.*?)"', body)
        if not image_match or not z21id_match or not pages_match:
            continue

        image_file_name = decode_js_string(image_match.group("value"))
        z21id = decode_js_string(z21id_match.group("value"))
        pages_value = decode_js_string(pages_match.group("value"))
        page_count_match = re.search(r"\^N(\d+)", pages_value)
        if not page_count_match:
            continue

        title = unquote(image_file_name).replace("\\", "/").lstrip("/")
        records.append(
            WorkRecord(
                mfn=mfn,
                image_file_name=image_file_name,
                z21id=z21id,
                page_count=int(page_count_match.group(1)),
                title=title,
            )
        )

    return records


async def fetch_search_html(search_url: str, fallback_file: Path | None, click_viewers: bool) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        try:
            await page.goto(search_url, wait_until="networkidle", timeout=60_000)
            if click_viewers:
                viewers = page.locator("text=Постраничный просмотр полного текста")
                count = await viewers.count()
                print(f"Found {count} page-viewer buttons")
                for index in range(count):
                    button = viewers.nth(index)
                    try:
                        await button.scroll_into_view_if_needed(timeout=5_000)
                        await button.click(timeout=10_000)
                        await page.wait_for_timeout(400)
                    except PlaywrightTimeoutError:
                        print(f"Warning: could not click viewer button #{index + 1}", file=sys.stderr)
            return await page.content()
        except Exception as exc:
            if fallback_file and fallback_file.exists():
                print(f"Warning: live browser fetch failed ({exc}); using {fallback_file}", file=sys.stderr)
                return fallback_file.read_text(encoding="utf-8", errors="replace")
            raise
        finally:
            await browser.close()


def download_page(record: WorkRecord, page_number: int, destination: Path, referer: str, retries: int = 3) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return True

    url = IMAGE_URL.format(
        image_file_name=record.image_file_name,
        mfn=record.mfn,
        z21id=record.z21id,
        page=page_number,
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": referer,
    }
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=20) as response:
                data = response.read()
            if len(data) < 1000:
                raise ValueError(f"short response: {len(data)} bytes")
            destination.write_bytes(data)
            return True
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            if attempt == retries:
                print(f"Warning: failed {url}: {exc}", file=sys.stderr)
                return False
            print(f"Retrying page after error: {exc}", file=sys.stderr)
    return False


def validate_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (UnidentifiedImageError, OSError):
        return False


def build_pdf(image_paths: list[Path], output_pdf: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output_pdf), pageCompression=1)
    for image_path in image_paths:
        with Image.open(image_path) as image:
            width, height = image.size
        pdf.setPageSize((width, height))
        pdf.drawImage(ImageReader(str(image_path)), 0, 0, width=width, height=height)
        pdf.showPage()
    pdf.save()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download SHSPU IRBIS VKR page images and build one PDF per VKR record."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=SEARCH_URL,
        help="Search results URL from the SHSPU library. Defaults to the original VKR query.",
    )
    parser.add_argument(
        "--url",
        dest="url_option",
        help="Search results URL from the SHSPU library. Overrides the positional URL.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/pdf/shspu_vkr"),
        help="Directory where separate VKR PDF files will be saved.",
    )
    parser.add_argument("--fallback-html", type=Path, default=Path("search.html"))
    parser.add_argument(
        "--images-dir",
        type=Path,
        help="Directory for downloaded page images. Defaults to OUTPUT_DIR/_images.",
    )
    parser.add_argument(
        "--combined-output",
        type=Path,
        help="Optional path for an additional combined PDF with all found VKR records.",
    )
    parser.add_argument("--no-click", action="store_true")
    args = parser.parse_args()

    search_url = args.url_option or args.url
    images_dir = args.images_dir or default_images_dir(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    html = await fetch_search_html(search_url, args.fallback_html, click_viewers=not args.no_click)
    records = parse_records(html)
    if not records:
        raise SystemExit("No VKR records with page images were found")

    print(f"Parsed {len(records)} VKR records")
    all_image_paths: list[Path] = []
    failed_pages: list[str] = []
    written_pdfs: list[Path] = []

    for record_index, record in enumerate(records, start=1):
        basename = record_basename(record_index, record)
        record_dir = images_dir / record_images_basename(record_index, record)
        record_image_paths: list[Path] = []
        print(f"Downloading MFN {record.mfn}: {record.page_count} pages ({record.title})")
        for page_number in range(1, record.page_count + 1):
            image_path = record_dir / f"page_{page_number:04d}.jpg"
            ok = download_page(record, page_number, image_path, search_url) and validate_image(image_path)
            if ok:
                record_image_paths.append(image_path)
                all_image_paths.append(image_path)
            else:
                failed_pages.append(f"MFN {record.mfn} page {page_number}")
            if page_number % 10 == 0 or page_number == record.page_count:
                print(f"  {page_number}/{record.page_count}")

        if record_image_paths:
            output_pdf = args.output_dir / f"{basename}.pdf"
            build_pdf(record_image_paths, output_pdf)
            written_pdfs.append(output_pdf)
            print(f"PDF written: {output_pdf} ({len(record_image_paths)} pages)")

    if not all_image_paths:
        raise SystemExit("No images were downloaded")

    if args.combined_output:
        build_pdf(all_image_paths, args.combined_output)
        print(f"Combined PDF written: {args.combined_output} ({len(all_image_paths)} pages)")

    print(f"Done: {len(written_pdfs)} separate PDF files in {args.output_dir}")
    if failed_pages:
        print(f"Failed pages: {len(failed_pages)}", file=sys.stderr)
        for item in failed_pages[:20]:
            print(f"  {item}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
