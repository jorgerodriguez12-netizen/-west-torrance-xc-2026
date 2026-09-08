import io, re, hashlib, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
RESULTS = DATA / "results.csv"
MEETS = DATA / "meets.csv"
PARSER_VERSION = DATA / "parser_version.txt"

HEADERS = {"User-Agent": "WestTorranceXC-ResultsBot/2.0 (coaching analytics)"}
RESULT_COLUMNS = ["result_id","date","meet","city","gender","race","distance_m","athlete","grade",
                  "team","time_sec","time","place","points","course","source_url"]
MEET_COLUMNS = ["meet_id","date","meet","city","source_url","status"]

def get(url, timeout=(8, 20)):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r

def time_sec(s):
    p = s.strip().split(":")
    return int(p[0]) * 60 + float(p[1]) if len(p) == 2 else float(p[0])

def normalize_space(s):
    return re.sub(r"\s+", " ", s).strip()

def parse_race_header(text):
    m = re.search(r"Race\s+\d+\s*-\s*(Boys|Girls)\s+(.+?)\s*-\s*([0-9]+(?:\.[0-9]+)?\s*(?:Mile|Miles|K|5K))",
                  text, re.I)
    if not m:
        return None
    gender = m.group(1).title()
    race = m.group(2).strip()
    raw = m.group(3).lower().replace(" ", "")
    if "mile" in raw:
        dist = round(float(re.search(r"[0-9.]+", raw).group()) * 1609.344)
    elif raw in ("5k", "5.0k"):
        dist = 5000
    else:
        dist = round(float(raw[:-1]) * 1000)
    return gender, race, dist

# Finished Results PDFs sometimes put two adjacent runner records on one
# extracted line. We therefore find every complete record inside each chunk,
# rather than assuming one line == one runner.
ROW_RE = re.compile(
    r"(?P<place>\d+)\s+"
    r"(?P<athlete>.+?)\s+"
    r"(?P<grade>9|10|11|12)\s+"
    r"(?P<team>.+?)\s+"
    r"(?P<time>\d+:\d{2}(?:\.\d+)?)"
    r"(?:\s+(?P<points>\d+))?"
    r"(?=\s+\d+\s+|$)"
)

def parse_pdf(pdf_bytes, source_url, meet_name, meet_date):
    rows = []
    with __import__("pdfplumber").open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text = [(p.extract_text() or "") for p in pdf.pages]
    full = "\n".join(pages_text)
    hdr = parse_race_header(full)
    if not hdr:
        return rows
    gender, race, dist = hdr

    lines = [normalize_space(x) for x in full.splitlines() if normalize_space(x)]
    start = next((i + 1 for i, l in enumerate(lines) if "Individual Results" in l), 0)

    chunks, cur = [], ""
    for line in lines[start:]:
        if line.startswith("Race ") or line.startswith("Team Results"):
            continue
        if re.match(r"^\d+\s+", line):
            if cur:
                chunks.append(cur)
            cur = line
        elif cur:
            cur += " " + line
    if cur:
        chunks.append(cur)

    for chunk in chunks:
        for m in ROW_RE.finditer(chunk):
            place = int(m.group("place"))
            athlete = normalize_space(m.group("athlete"))
            grade = int(m.group("grade"))
            team = normalize_space(m.group("team"))
            tm = m.group("time")
            points = m.group("points") or ""
            # Reject obvious extraction artifacts.
            if len(athlete) < 2 or len(team) < 2:
                continue
            if len(athlete) > 60 or len(team) > 70:
                continue
            if any(x in athlete.lower() for x in ("place name grade", "individual results")):
                continue
            try:
                sec = time_sec(tm)
            except Exception:
                continue
            rid = hashlib.sha1(
                f"{meet_date}|{meet_name}|{race}|{place}|{athlete}|{team}|{tm}".encode()
            ).hexdigest()
            rows.append({
                "result_id": rid, "date": meet_date, "meet": meet_name, "city": "",
                "gender": gender, "race": race, "distance_m": dist, "athlete": athlete,
                "grade": grade, "team": team, "time_sec": sec, "time": tm, "place": place,
                "points": int(points) if points else "", "course": "", "source_url": source_url
            })
    return rows

def discover_meets():
    url = "https://www.finishedresults.com/results?season=xc&year=2026"
    soup = BeautifulSoup(get(url).text, "html.parser")
    found = []
    for a in soup.find_all("a"):
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

def parse_meet_page(date, display_text, meet_url):
    soup = BeautifulSoup(get(meet_url).text, "html.parser")
    meet_name = display_text
    h1 = soup.find(["h1", "h2"])
    if h1:
        meet_name = normalize_space(h1.get_text(" ", strip=True))
    pdfs = []
    for a in soup.find_all("a", href=True):
        href = urljoin(meet_url, a["href"])
        if ".pdf" in href.lower():
            pdfs.append(href)
    rows = []
    for pdf in dict.fromkeys(pdfs):
        try:
            rows.extend(parse_pdf(get(pdf).content, pdf, meet_name, date))
        except Exception as e:
            print("PDF failed:", pdf, e, flush=True)
    return meet_name, "", rows

def main():
    # Full rebuild once, then incremental runs use the same parser.
    # Existing malformed rows are intentionally discarded on this version.
    existing = pd.DataFrame(columns=RESULT_COLUMNS)
    allrows, meets = [], []

    for date, name, url in discover_meets():
        print("Meet:", date, name, flush=True)
        try:
            meet_name, city, rows = parse_meet_page(date, name, url)
            allrows.extend(rows)
            meets.append({
                "meet_id": hashlib.sha1(url.encode()).hexdigest()[:16],
                "date": date, "meet": meet_name, "city": city,
                "source_url": url, "status": "results discovered"
            })
            print("  rows:", len(rows), flush=True)
        except Exception as e:
            print("Meet failed:", e, flush=True)
        time.sleep(0.2)

    new = pd.DataFrame(allrows, columns=RESULT_COLUMNS)
    if not new.empty:
        new = new.drop_duplicates(subset=["result_id"], keep="last")
        new.to_csv(RESULTS, index=False)

    if meets:
        pd.DataFrame(meets, columns=MEET_COLUMNS).drop_duplicates("meet_id").to_csv(MEETS, index=False)

    PARSER_VERSION.write_text("2.1-global-record-parser\n")
    print("Imported rows:", len(new), "Total stored:", len(new), flush=True)

if __name__ == "__main__":
    main()
