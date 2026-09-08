import io
import os
import re
import hashlib
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import pdfplumber
import pandas as pd

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

RESULTS = DATA / "results.csv"
MEETS = DATA / "meets.csv"
PARSER_VERSION = DATA / "parser_version.txt"
CURRENT_VERSION = "2"

HEADERS = {
    "User-Agent": "WestTorranceXC-ResultsBot/2.0 (coaching analytics)"
}

RESULT_COLUMNS = [
    "result_id", "date", "meet", "city", "gender", "race", "distance_m",
    "athlete", "grade", "team", "time_sec", "time", "place", "points",
    "course", "source_url"
]

MEET_COLUMNS = ["meet_id", "date", "meet", "city", "source_url", "status"]


def get(url, timeout=(8, 20)):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def normalize_space(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def time_sec(s):
    s = s.strip()
    parts = s.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def parse_race_header(text):
    m = re.search(
        r"Race\s+\d+\s*-\s*(Boys|Girls)\s+(.+?)\s*-\s*"
        r"([0-9]+(?:\.[0-9]+)?\s*(?:Mile|Miles|K|5K))",
        text,
        re.I,
    )
    if not m:
        return None

    gender = m.group(1).title()
    race = normalize_space(m.group(2))
    raw = m.group(3).lower().replace(" ", "")

    if "mile" in raw:
        dist = round(float(re.search(r"[0-9.]+", raw).group()) * 1609.344)
    elif raw in ("5k", "5.0k"):
        dist = 5000
    else:
        dist = round(float(raw[:-1]) * 1000)

    return gender, race, dist


# Finished Results PDFs sometimes extract several runners on one PDF text line.
# Instead of assuming one physical line == one runner, scan the entire individual
# results text for repeated: place -> name -> grade -> team -> time -> points.
RUNNER_RE = re.compile(
    r"(?P<place>\d+)\s+"
    r"(?P<athlete>.*?)\s+"
    r"(?P<grade>\d{1,2})\s+"
    r"(?P<team>.*?)\s+"
    r"(?P<time>\d+:\d{2}(?:\.\d+)?)"
    r"(?:\s+(?P<points>\d+))?"
    r"(?=\s+\d+\s+|$)",
    re.S,
)


def clean_field(value):
    value = normalize_space(value)
    # Remove obvious page/footer fragments that can leak into a field.
    value = re.sub(r"\bPage\s+\d+/\d+\b", "", value, flags=re.I)
    value = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?:am|pm)\b", "", value, flags=re.I)
    return normalize_space(value)


def parse_pdf(pdf_bytes, source_url, meet_name, meet_date):
    rows = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [(p.extract_text(x_tolerance=2, y_tolerance=3) or "") for p in pdf.pages]

    full = "\n".join(pages)
    header = parse_race_header(full)
    if not header:
        return rows

    gender, race, dist = header

    # Only parse the Individual Results section. This prevents team-score tables
    # from being interpreted as individual runners.
    marker = re.search(r"\bIndividual Results\b", full, re.I)
    if not marker:
        return rows

    individual = full[marker.end():]
    # Remove repeated section headers from later pages.
    individual = re.sub(
        r"Race\s+\d+\s*-\s*(?:Boys|Girls).*?\n.*?\bIndividual Results\b",
        " ",
        individual,
        flags=re.I | re.S,
    )
    individual = normalize_space(individual)

    for m in RUNNER_RE.finditer(individual):
        try:
            place = int(m.group("place"))
            grade = int(m.group("grade"))
            athlete = clean_field(m.group("athlete"))
            team = clean_field(m.group("team"))
            tm = m.group("time")
            points = m.group("points") or ""
            sec = time_sec(tm)
        except Exception:
            continue

        # Basic sanity checks keep headers/footer fragments out.
        if not athlete or not team:
            continue
        if len(athlete) < 2 or len(athlete) > 80:
            continue
        if len(team) < 2 or len(team) > 100:
            continue
        if not (1 <= grade <= 12):
            continue
        if not (1 <= place <= 2000):
            continue

        # If the regex accidentally captured a second place number inside a
        # team/name field, reject the row rather than polluting the database.
        if re.search(r"\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s+\d{1,2}\s+", team):
            continue

        rid = hashlib.sha1(
            f"{meet_date}|{meet_name}|{race}|{place}|{athlete}|{team}|{tm}".encode()
        ).hexdigest()

        rows.append({
            "result_id": rid,
            "date": meet_date,
            "meet": meet_name,
            "city": "",
            "gender": gender,
            "race": race,
            "distance_m": dist,
            "athlete": athlete,
            "grade": grade,
            "team": team,
            "time_sec": sec,
            "time": tm,
            "place": place,
            "points": int(points) if points else "",
            "course": "",
            "source_url": source_url,
        })

    return rows


def discover_meets():
    url = "https://www.finishedresults.com/results?season=xc&year=2026"
    soup = BeautifulSoup(get(url).text, "html.parser")
    found = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        txt = normalize_space(a.get_text(" ", strip=True))
        if "View Results" not in txt:
            continue

        link = urljoin(url, href)
        parent = a.find_parent("tr")
        text = normalize_space(parent.get_text(" ", strip=True)) if parent else txt

        dm = re.search(r"(\d{2}/\d{2}/2026)", text)
        if not dm:
            continue

        date = pd.to_datetime(
            dm.group(1), format="%m/%d/%Y"
        ).date().isoformat()

        name = text.replace("View Results", "").strip()
        name = re.sub(r"^\d{2}/\d{2}/2026\s*", "", name)
        name = re.sub(r"\s+View Results.*$", "", name)

        found.append((date, name, link))

    out = []
    seen = set()
    for item in found:
        if item[2] not in seen:
            out.append(item)
            seen.add(item[2])

    return out


def parse_meet_page(date, display_text, meet_url, already_processed):
    soup = BeautifulSoup(get(meet_url).text, "html.parser")

    meet_name = display_text
    h1 = soup.find(["h1", "h2"])
    if h1:
        meet_name = normalize_space(h1.get_text(" ", strip=True))

    pdfs = []
    for a in soup.find_all("a", href=True):
        href = urljoin(meet_url, a["href"])
        if ".pdf" in href.lower() and "XC2026" in href:
            pdfs.append(href)

    rows = []
    attempted = 0

    for pdf in dict.fromkeys(pdfs):
        if pdf in already_processed:
            continue

        attempted += 1
        try:
            b = get(pdf).content
            parsed = parse_pdf(b, pdf, meet_name, date)
            if parsed:
                rows.extend(parsed)
                print(f"  OK {len(parsed):4d} rows  {pdf}")
            else:
                print(f"  SKIP no individual rows  {pdf}")
        except Exception as e:
            print(f"  PDF failed {pdf}: {e}")

    return meet_name, rows, pdfs, attempted


def load_existing():
    if not RESULTS.exists() or RESULTS.stat().st_size == 0:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    df = pd.read_csv(RESULTS)
    for c in RESULT_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[RESULT_COLUMNS]


def main():
    rebuild = True
    if PARSER_VERSION.exists():
        rebuild = PARSER_VERSION.read_text().strip() != CURRENT_VERSION

    existing = load_existing()

    # First run with parser v2 intentionally rebuilds the database so corrupt
    # rows produced by parser v1 are removed. Later runs are incremental.
    if rebuild:
        print("Parser v2 rebuild: replacing old parsed results.")
        existing = pd.DataFrame(columns=RESULT_COLUMNS)
        already_processed = set()
    else:
        already_processed = set()
        if RESULTS.exists() and RESULTS.stat().st_size:
            existing_sources = existing["source_url"].dropna().astype(str)
            already_processed = set(x for x in existing_sources if x.startswith("http"))
        print(f"Incremental update. Existing rows: {len(existing):,}")

    meets = []
    allrows = []

    for date, name, url in discover_meets():
        print(f"Meet: {date} | {name}")

        try:
            meet_name, rows, pdfs, attempted = parse_meet_page(
                date, name, url, already_processed
            )
            allrows.extend(rows)

            meets.append({
                "meet_id": hashlib.sha1(url.encode()).hexdigest()[:16],
                "date": date,
                "meet": meet_name,
                "city": "",
                "source_url": url,
                "status": f"{len(pdfs)} PDFs / {attempted} new",
            })

        except Exception as e:
            print(f"Meet failed: {e}")

    new = pd.DataFrame(allrows, columns=RESULT_COLUMNS)

    combined = pd.concat([existing, new], ignore_index=True)

    if not combined.empty:
        combined = combined.drop_duplicates(
            subset=["result_id"], keep="last"
        )
        # Keep rows sorted so the CSV remains predictable.
        combined = combined.sort_values(
            ["date", "gender", "race", "place", "athlete"],
            na_position="last",
        )
        combined.to_csv(RESULTS, index=False)

    if meets:
        md = pd.DataFrame(meets, columns=MEET_COLUMNS)
        md.to_csv(MEETS, index=False)

    PARSER_VERSION.write_text(CURRENT_VERSION)

    total = len(combined)
    print(f"Imported rows this run: {len(new):,}")
    print(f"Total stored rows:       {total:,}")


if __name__ == "__main__":
    main()
