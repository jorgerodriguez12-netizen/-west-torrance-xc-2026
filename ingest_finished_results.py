import io
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
CURRENT_VERSION = "3"

HEADERS = {"User-Agent": "WestTorranceXC-ResultsBot/3.0 (coaching analytics)"}

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
    p = s.strip().split(":")
    return int(p[0]) * 60 + float(p[1]) if len(p) == 2 else float(p[0])


def parse_race_header(text):
    m = re.search(
        r"Race\s+\d+\s*-\s*(Boys|Girls)\s+(.+?)\s*-\s*"
        r"([0-9]+(?:\.[0-9]+)?\s*(?:Mile|Miles|K|5K))",
        text, re.I
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


# A PDF may place two runners on one extracted line. This parser treats a
# time as the end of a runner record and requires the next record to begin
# with a place number followed by a capitalized name.
RUNNER_RE = re.compile(
    r"(?P<place>\d+)\s+"
    r"(?P<athlete>.*?)\s+"
    r"(?P<grade>\d{1,2})\s+"
    r"(?P<team>.*?)\s+"
    r"(?P<time>\d+:\d{2}(?:\.\d+)?)"
    r"(?:\s+(?P<points>\d+))?"
    r"(?=\s+\d+\s+[A-Z]|$)",
    re.S
)


def clean_field(s):
    s = normalize_space(s)
    s = re.sub(r"\bPage\s+\d+/\d+\b", "", s, flags=re.I)
    return normalize_space(s)


def parse_pdf(pdf_bytes, source_url, meet_name, meet_date):
    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full = "\n".join(
            p.extract_text(x_tolerance=2, y_tolerance=3) or ""
            for p in pdf.pages
        )

    header = parse_race_header(full)
    marker = re.search(r"\bIndividual Results\b", full, re.I)
    if not header or not marker:
        return rows

    gender, race, dist = header
    individual = full[marker.end():]

    # Remove repeated headers while retaining the individual result records.
    individual = re.sub(
        r"Race\s+\d+\s*-\s*(?:Boys|Girls).*?\bIndividual Results\b",
        " ",
        individual,
        flags=re.I | re.S
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

        if not athlete or not team:
            continue
        if not (2 <= len(athlete) <= 80 and 2 <= len(team) <= 100):
            continue
        if not (1 <= grade <= 12 and 1 <= place <= 2000):
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
        txt = normalize_space(a.get_text(" ", strip=True))
        if "View Results" not in txt:
            continue
        link = urljoin(url, a["href"])
        parent = a.find_parent("tr")
        text = normalize_space(parent.get_text(" ", strip=True)) if parent else txt
        dm = re.search(r"(\d{2}/\d{2}/2026)", text)
        if not dm:
            continue

        date = pd.to_datetime(dm.group(1), format="%m/%d/%Y").date().isoformat()
        name = re.sub(r"^\d{2}/\d{2}/2026\s*", "", text.replace("View Results", "").strip())
        name = re.sub(r"\s+View Results.*$", "", name)
        found.append((date, name, link))

    out, seen = [], set()
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

    rows, attempted = [], 0
    for pdf in dict.fromkeys(pdfs):
        if pdf in already_processed:
            continue
        attempted += 1
        try:
            parsed = parse_pdf(get(pdf).content, pdf, meet_name, date)
            rows.extend(parsed)
            print(f"OK {len(parsed)} rows | {pdf}")
        except Exception as e:
            print(f"PDF failed {pdf}: {e}")

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
    rebuild = not PARSER_VERSION.exists() or PARSER_VERSION.read_text().strip() != CURRENT_VERSION
    existing = load_existing()

    if rebuild:
        print("Parser v3 rebuild: replacing old parsed results.")
        existing = pd.DataFrame(columns=RESULT_COLUMNS)
        already_processed = set()
    else:
        already_processed = set(existing["source_url"].dropna().astype(str))
        already_processed = {x for x in already_processed if x.startswith("http")}

    meets, allrows = [], []

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
        combined = combined.drop_duplicates("result_id", keep="last")
        combined = combined.sort_values(
            ["date", "gender", "race", "place", "athlete"],
            na_position="last"
        )
        combined.to_csv(RESULTS, index=False)

    if meets:
        pd.DataFrame(meets, columns=MEET_COLUMNS).to_csv(MEETS, index=False)

    PARSER_VERSION.write_text(CURRENT_VERSION)
    print(f"Imported rows this run: {len(new):,}")
    print(f"Total stored rows: {len(combined):,}")


if __name__ == "__main__":
    main()
