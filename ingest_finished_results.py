import io, re, csv, hashlib, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import pdfplumber
import pandas as pd

BASE=Path(__file__).parent
DATA=BASE/"data"; DATA.mkdir(exist_ok=True)
RESULTS=DATA/"results.csv"; MEETS=DATA/"meets.csv"
HEADERS={"User-Agent":"WestTorranceXC-ResultsBot/1.0 (coaching analytics)"}

RESULT_COLUMNS=["result_id","date","meet","city","gender","race","distance_m","athlete","grade","team","time_sec","time","place","points","course","source_url"]
MEET_COLUMNS=["meet_id","date","meet","city","source_url","status"]

def get(url):
    r=requests.get(url,headers=HEADERS,timeout=30)
    r.raise_for_status()
    return r

def time_sec(s):
    s=s.strip()
    p=s.split(":")
    if len(p)==2:return int(p[0])*60+float(p[1])
    return float(p[0])

def parse_race_header(text):
    m=re.search(r"Race\s+\d+\s*-\s*(Boys|Girls)\s+(.+?)\s*-\s*([0-9]+(?:\.[0-9]+)?\s*(?:Mile|Miles|K|5K))",text,re.I)
    if not m:return None
    gender=m.group(1).title(); race=m.group(2).strip(); raw=m.group(3).lower().replace(" ","")
    if "mile" in raw: dist=round(float(re.search(r"[0-9.]+",raw).group())*1609.344)
    elif raw=="5k" or raw=="5.0k": dist=5000
    else: dist=round(float(raw[:-1])*1000)
    return gender,race,dist

def normalize_space(s): return re.sub(r"\s+"," ",s).strip()

def parse_pdf(pdf_bytes,source_url,meet_name,meet_date):
    rows=[]
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full="\n".join((p.extract_text() or "") for p in pdf.pages)
    hdr=parse_race_header(full)
    if not hdr:return rows
    gender,race,dist=hdr
    # Individual-results section rows. Finished Results PDFs put place/name/grade/team/time/points in order.
    lines=[normalize_space(x) for x in full.splitlines() if normalize_space(x)]
    start=0
    for i,l in enumerate(lines):
        if "Individual Results" in l:
            start=i+1
            break
    block=lines[start:]
    # Each row starts with a place number. Wrapped PDF lines are joined until next place.
    chunks=[]; cur=""
    for l in block:
        if re.match(r"^\d+\s+",l):
            if cur: chunks.append(cur)
            cur=l
        elif cur:
            # Stop when a new section begins.
            if l.startswith("Team Results") or l.startswith("Race "): 
                continue
            cur += " "+l
    if cur: chunks.append(cur)
    row_re=re.compile(r"^(\d+)\s+(.+?)\s+(\d{1,2})\s+(.+?)\s+(\d+:\d{2}(?:\.\d+)?)\s*(\d+)?$")
    for chunk in chunks:
        m=row_re.match(chunk)
        if not m: continue
        place=int(m.group(1)); athlete=normalize_space(m.group(2)); grade=int(m.group(3))
        team=normalize_space(m.group(4)); tm=m.group(5); points=m.group(6)
        # Guard against header-like false positives.
        if len(athlete)<2 or len(team)<2: continue
        try: sec=time_sec(tm)
        except: continue
        rid=hashlib.sha1(f"{meet_date}|{meet_name}|{race}|{place}|{athlete}|{team}|{tm}".encode()).hexdigest()
        rows.append({"result_id":rid,"date":meet_date,"meet":meet_name,"city":"","gender":gender,
                     "race":race,"distance_m":dist,"athlete":athlete,"grade":grade,"team":team,
                     "time_sec":sec,"time":tm,"place":place,"points":int(points) if points else "",
                     "course":"","source_url":source_url})
    return rows

def discover_meets():
    url="https://www.finishedresults.com/results?season=xc&year=2026"
    soup=BeautifulSoup(get(url).text,"html.parser")
    found=[]
    for a in soup.find_all("a"):
        href=a.get("href","")
        txt=normalize_space(a.get_text(" ",strip=True))
        if "View Results" not in txt: continue
        link=urljoin(url,href)
        # Find nearby date/name text from parent row.
        parent=a.find_parent("tr")
        text=normalize_space(parent.get_text(" ",strip=True)) if parent else txt
        dm=re.search(r"(\d{2}/\d{2}/2026)",text)
        if not dm: continue
        date=pd.to_datetime(dm.group(1),format="%m/%d/%Y").date().isoformat()
        # Best effort: strip date/location boilerplate.
        name=text.replace("View Results","").strip()
        name=re.sub(r"^\d{2}/\d{2}/2026\s*","",name)
        name=re.sub(r"\s+View Results.*$","",name)
        found.append((date,name,link))
    # dedupe URLs
    out=[]; seen=set()
    for x in found:
        if x[2] not in seen: out.append(x); seen.add(x[2])
    return out

def parse_meet_page(date,display_text,meet_url):
    soup=BeautifulSoup(get(meet_url).text,"html.parser")
    meet_name=display_text
    city=""
    # Use page title/header where possible.
    h1=soup.find(["h1","h2"])
    if h1: meet_name=normalize_space(h1.get_text(" ",strip=True))
    pdfs=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(meet_url,a["href"])
        if ".pdf" in href.lower(): pdfs.append(href)
    rows=[]
    for pdf in dict.fromkeys(pdfs):
        try:
            b=get(pdf).content
            rows.extend(parse_pdf(b,pdf,meet_name,date))
        except Exception as e:
            print("PDF failed",pdf,e)
    return meet_name,city,rows,pdfs

def main():
    existing=pd.read_csv(RESULTS) if RESULTS.exists() and RESULTS.stat().st_size else pd.DataFrame(columns=RESULT_COLUMNS)
    for c in RESULT_COLUMNS:
        if c not in existing.columns: existing[c]=""
    meets=[]
    allrows=[]
    for date,name,url in discover_meets():
        print("Meet:",date,name,url)
        try:
            meet_name,city,rows,pdfs=parse_meet_page(date,name,url)
            allrows.extend(rows)
            meets.append({"meet_id":hashlib.sha1(url.encode()).hexdigest()[:16],"date":date,"meet":meet_name,
                          "city":city,"source_url":url,"status":"results discovered"})
        except Exception as e:
            print("Meet failed:",e)
        time.sleep(.3)
    new=pd.DataFrame(allrows,columns=RESULT_COLUMNS)
    if not new.empty:
        combined=pd.concat([existing,new],ignore_index=True)
        combined=combined.drop_duplicates(subset=["result_id"],keep="last")
        combined.to_csv(RESULTS,index=False)
    md=pd.DataFrame(meets,columns=MEET_COLUMNS)
    if not md.empty: md.drop_duplicates("meet_id").to_csv(MEETS,index=False)
    print("Imported rows:",len(new),"Total stored:",len(pd.read_csv(RESULTS)) if RESULTS.exists() else 0)

if __name__=="__main__": main()
