# -*- coding: utf-8 -*-
"""
블로그 RSS → 시공사례 갤러리 자동 갱신
- 두 네이버 블로그(supermans8157, superman1187)의 RSS에서 새 글을 찾아
  대표 사진을 내려받고 assets/gallery-data.js 를 갱신한다.
- 카테고리별 최신 KEEP_PER_CAT 건만 유지. 자동 수집 이미지(auto/)는 미참조분 삭제.
GitHub Actions 에서 매일 실행 (로컬 수동 실행도 가능: python scripts/update_gallery.py)
"""
import json, re, os, sys, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "assets", "gallery-data.js")
AUTO_DIR = os.path.join(ROOT, "assets", "gallery", "auto")
BLOGS = ["supermans8157", "superman1187"]
KEEP_PER_CAT = 10
KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"

def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = r.read()
    return d if binary else d.decode("utf-8", errors="replace")

def classify(cat_name, title):
    s = f"{cat_name} {title}"
    if any(k in s for k in ("로봇", "로청", "로보락", "드리미", "나르왈", "직배수")): return "robot"
    if any(k in s for k in ("연마", "광택", "디딤석", "UV", "uv")): return "polish"
    if any(k in s for k in ("타공", "절단", "메꿈", "구멍", "아트월", "인덕션")): return "cutting"
    if any(k in s for k in ("깨짐", "크랙", "실금", "상판수리", "상판 수리", "금이", "금 간")): return "crack"
    if any(k in s for k in ("후드", "싱크볼", "수전")): return "hood_sink"
    return "reform"

def cover_image(blog_id, log_no):
    html = fetch(f"https://m.blog.naver.com/{blog_id}/{log_no}").replace("&amp;", "&")
    for u in re.findall(r'https://(?:mblogthumb-phinf|postfiles|blogfiles)\.pstatic\.net/[^"\'\s<>]+', html):
        p = u.split("?")[0]
        if p.lower().endswith(".gif") or "profileimage" in p.lower():
            continue
        return p + "?type=w800"
    return None

def parse_date_str(d):
    m = re.match(r"(\d{4})\. ?(\d{1,2})\. ?(\d{1,2})", d or "")
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=KST)
    return datetime.now(KST)  # "N시간 전" 등은 오늘로 간주

def load_existing():
    raw = open(DATA, encoding="utf-8").read()
    return json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))

def main():
    gallery = load_existing()
    known = {g["u"].rstrip("/").split("/")[-1] for g in gallery}
    for g in gallery:
        g.setdefault("ts", parse_date_str(g.get("d")).isoformat())

    os.makedirs(AUTO_DIR, exist_ok=True)
    added = 0
    for blog in BLOGS:
        try:
            rss = fetch(f"https://rss.blog.naver.com/{blog}.xml")
            root = ET.fromstring(rss)
        except Exception as e:
            print(f"[{blog}] RSS 실패: {e}")
            continue
        for item in root.iter("item"):
            link = (item.findtext("guid") or item.findtext("link") or "").split("?")[0].rstrip("/")
            log_no = link.split("/")[-1]
            if not log_no.isdigit():
                continue
            title = (item.findtext("title") or "").strip()
            cat_name = (item.findtext("category") or "").strip()
            pub = item.findtext("pubDate")
            try:
                dt = parsedate_to_datetime(pub).astimezone(KST)
            except Exception:
                dt = datetime.now(KST)
            if log_no in known:
                # 기존 항목의 상대 날짜("N시간 전")를 확정 날짜로 보정
                for g in gallery:
                    if g["u"].rstrip("/").endswith(log_no) and not re.match(r"\d{4}\.", g.get("d", "")):
                        g["d"] = f"{dt.year}. {dt.month}. {dt.day}."
                        g["ts"] = dt.isoformat()
                continue
            try:
                img_url = cover_image(blog, log_no)
                if not img_url:
                    print(f"[{blog}] {log_no} 이미지 없음 — 건너뜀")
                    continue
                data = fetch(img_url, binary=True)
                if len(data) < 3000:
                    continue
                fn = f"{log_no}.jpg"
                with open(os.path.join(AUTO_DIR, fn), "wb") as f:
                    f.write(data)
            except Exception as e:
                print(f"[{blog}] {log_no} 수집 실패: {e}")
                continue
            gallery.append({
                "c": classify(cat_name, title),
                "t": title,
                "d": f"{dt.year}. {dt.month}. {dt.day}.",
                "u": f"https://blog.naver.com/{blog}/{log_no}",
                "img": f"assets/gallery/auto/{fn}",
                "ts": dt.isoformat(),
            })
            known.add(log_no)
            added += 1
            print(f"[{blog}] + {title[:40]}")
            time.sleep(0.4)

    # 카테고리별 최신 KEEP_PER_CAT 건 유지
    gallery.sort(key=lambda g: g["ts"], reverse=True)
    kept, count = [], {}
    for g in gallery:
        c = g["c"]
        count[c] = count.get(c, 0) + 1
        if count[c] <= KEEP_PER_CAT:
            kept.append(g)

    # auto/ 폴더에서 더 이상 참조되지 않는 이미지 삭제
    used = {os.path.basename(g["img"]) for g in kept if "/auto/" in g["img"]}
    removed = 0
    for fn in os.listdir(AUTO_DIR):
        if fn not in used:
            os.remove(os.path.join(AUTO_DIR, fn))
            removed += 1

    with open(DATA, "w", encoding="utf-8") as f:
        f.write("const GALLERY = " + json.dumps(kept, ensure_ascii=False, indent=0) + ";")
    print(f"완료: 신규 {added}건, 유지 {len(kept)}건, 이미지 정리 {removed}건")

if __name__ == "__main__":
    main()
