import os
import re
import time
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SEEN_FILE = "data/seen_items.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

EXCLUDE_KEYWORDS = [
    "ziyaret etti", "ziyareti", "heyet", "çalıştay", "yemin ederek",
    "atama kararları", "atanan", "seçildi", "vefat", "başsağlığı", "kutlama",
    "sınav", "personel alımı", "sözleşmeli personel", "mülakat",
    "staj", "eğitim programı", "sözlüğü", "sempozyum", "zirvesi",
    "bilim fuarları", "bilim söyleşileri"
]

EPDK_KEYWORDS = [
    "yekdem", "biyogaz", "biogas", "çöpgaz", "yenilenebilir enerji", "lng"
]

CATEGORIES = {
    "#KDV_Kurumlar": [
        "kdv", "katma değer vergisi", "kurumlar vergisi", "tevkifat",
        "vergi usul", "indirimli kurumlar", "yatırıma katkı", "enflasyon düzeltmesi",
        "matrah", "istisna", "muafiyet", "stopaj", "beyanname", "sirküler", "tebliğ", "gelir idaresi"
    ],
    "#Enerji_Tesvik": [
        "yekdem", "biyogaz", "biogas", "çöpgaz", "yenilenebilir enerji", "lng",
        "lisanssız", "güneş enerjisi", "ges", "rüzgar enerjisi", "depolamalı",
        "yeşil dönüşüm", "karbon", "enerji verimliliği", "biyokütle"
    ],
    "#Imalat_Sanayi": [
        "imalat", "yatırım teşvik", "bölgesel teşvik", "öncelikli yatırım",
        "stratejik yatırım", "organize sanayi", "osb", "makine ve teçhizat",
        "ihracat", "yerli malı", "kapasite raporu", "kosgeb", "hamle", "sanayi sicil"
    ],
    "#ArGe_Teknopark": [
        "ar-ge", "arge", "teknopark", "teknoloji geliştirme", "4691", "5746",
        "tübitak", "teydeb", "tasarım merkezi", "inovasyon", "girişim sermayesi",
        "yazılım", "bilişim", "patent", "ticarileşme", "teknokent", "destek çağrısı", "proje çağrısı", "çağrı"
    ]
}

def log(msg):
    print(msg, flush=True)

def get_tr_now():
    return datetime.now(timezone(timedelta(hours=3)))

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return set()
                return set(json.loads(content))
        except Exception:
            return set()
    return set()

def save_seen(seen_set):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    recent_list = list(seen_set)[-3000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(recent_list, f, ensure_ascii=False, indent=2)

def make_id(source, title):
    raw = f"{source}:{title[:100].strip().lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def tr_lower(text):
    return text.replace("İ", "i").replace("I", "ı").lower()

def has_word(text, kw):
    pattern = r'(?<![a-zçğıöşü0-9])' + re.escape(kw) + r'(?![a-zçğıöşü0-9])'
    return bool(re.search(pattern, text))

def match_categories(source, title):
    text = tr_lower(title)
    if any(bad in text for bad in EXCLUDE_KEYWORDS):
        return []
    
    if source == "EPDK":
        if any(has_word(text, kw) for kw in EPDK_KEYWORDS):
            return ["#Enerji_Tesvik"]
        return []

    matched = []
    for tag, kws in CATEGORIES.items():
        if any(has_word(text, kw) for kw in kws):
            matched.append(tag)
    return matched

def send_telegram(source, title, link, tags):
    if not BOT_TOKEN or not CHAT_ID:
        log("KRİTİK HATA: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik!")
        return False

    tag_str = " ".join(tags)
    today_str = get_tr_now().strftime("%d.%m.%Y")
    message = (
        f"📢 <b>YENİ MEVZUAT / TEŞVİK BİLDİRİMİ</b>\n\n"
        f"🏷️ <b>Kategori:</b> {tag_str}\n"
        f"🏛️ <b>Kaynak:</b> {source} ({today_str})\n"
        f"📌 <b>Başlık:</b> {title}\n\n"
        f"🔗 <a href='{link}'>Resmi Metne / Duyuruya Git</a>"
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=(5, 10))
        if r.status_code == 200:
            time.sleep(0.5)
            return True
        log(f"TELEGRAM HATA ({r.status_code}): {r.text}")
        return False
    except Exception as e:
        log(f"Telegram bağlantı hatası: {e}")
        return False

def scrape_google_site_rss(domain, source_name):
    items = []
    seen_titles = set()
    rss_url = f"https://news.google.com/rss/search?q=site:{domain}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        r = requests.get(rss_url, headers=HEADERS, timeout=(5, 10))
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el = item.find("link")
                if title_el is not None and link_el is not None:
                    raw_title = (title_el.text or "").split(" - ")[0].strip()
                    link = (link_el.text or "").strip()
                    norm = tr_lower(raw_title)
                    if len(raw_title) > 15 and norm not in seen_titles:
                        seen_titles.add(norm)
                        items.append((source_name, raw_title, link))
    except Exception:
        pass
    return items

def scrape_resmi_gazete(page):
    log("1/7 Resmî Gazete (Günlük Tam Sayı) taranıyor...")
    items = []
    seen_titles = set()
    now = get_tr_now()
    daily_url = f"https://www.resmigazete.gov.tr/eskiler/{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%Y%m%d')}.htm"
    
    for target in [daily_url, "https://www.resmigazete.gov.tr/"]:
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1500)
            links = page.query_selector_all("a")
            for a in links:
                title = " ".join((a.inner_text() or "").split())
                href = a.get_attribute("href") or ""
                if len(title) > 20 and (".htm" in href.lower() or ".pdf" in href.lower()):
                    norm = tr_lower(title)
                    if norm not in seen_titles and "önceki sayı" not in norm:
                        seen_titles.add(norm)
                        if href.startswith("http"):
                            full_link = href
                        elif href.startswith("/"):
                            full_link = f"https://www.resmigazete.gov.tr{href}"
                        else:
                            base_dir = target.rsplit("/", 1)[0]
                            full_link = f"{base_dir}/{href}"
                        items.append(("Resmî Gazete", title, full_link))
            if len(items) > 6:
                break
        except Exception:
            continue

    log(f"   -> Resmî Gazete tamam ({len(items)} kayıt).")
    return items

def scrape_gib(page):
    log("2/7 GİB taranıyor...")
    items = scrape_google_site_rss("gib.gov.tr", "Gelir İdaresi Bşk. (GİB)")
    if not items:
        try:
            page.goto("https://www.gib.gov.tr/duyurular", wait_until="domcontentloaded", timeout=12000)
            page.wait_for_timeout(1500)
            for a in page.query_selector_all("a"):
                title = " ".join((a.inner_text() or "").split())
                href = a.get_attribute("href") or ""
                if 20 < len(title) < 250 and any(k in href.lower() for k in ["duyuru", "sirkuler", "teblig"]):
                    full_link = href if href.startswith("http") else f"https://www.gib.gov.tr{href}"
                    items.append(("Gelir İdaresi Bşk. (GİB)", title, full_link))
        except Exception:
            pass
    log(f"   -> GİB tamam ({len(items)} kayıt).")
    return items

def scrape_sanayi(page):
    log("3/7 Sanayi Bakanlığı taranıyor...")
    items = scrape_google_site_rss("sanayi.gov.tr", "Sanayi ve Teknoloji Bak.")
    if not items:
        try:
            page.goto("https://www.sanayi.gov.tr/medya/duyurular", wait_until="domcontentloaded", timeout=12000)
            page.wait_for_timeout(1500)
            for a in page.query_selector_all("a"):
                title = " ".join((a.inner_text() or "").split())
                href = a.get_attribute("href") or ""
                if 22 < len(title) < 250 and any(k in href.lower() for k in ["duyuru", "haber", "mevzuat"]):
                    full_link = href if href.startswith("http") else f"https://www.sanayi.gov.tr{href}"
                    items.append(("Sanayi ve Teknoloji Bak.", title, full_link))
        except Exception:
            pass
    log(f"   -> Sanayi Bak. tamam ({len(items)} kayıt).")
    return items

def scrape_turmob():
    log("4/7 TÜRMOB (Mevzuat Sirküleri) taranıyor...")
    items = []
    seen_titles = set()
    try:
        resp = requests.get("https://www.turmob.org.tr/Mevzuat", headers=HEADERS, timeout=(5, 10), verify=False)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if 20 < len(title) < 260 and ("sirkuler" in href.lower() or "detay" in href.lower() or "mevzuat" in href.lower()):
                norm = tr_lower(title)
                if norm not in seen_titles:
                    seen_titles.add(norm)
                    full_link = href if href.startswith("http") else f"https://www.turmob.org.tr/{href.lstrip('/')}"
                    items.append(("TÜRMOB", title, full_link))
        log(f"   -> TÜRMOB tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> TÜRMOB atlandı: {e}")
    return items

def scrape_tubitak():
    log("5/7 TÜBİTAK taranıyor...")
    items = []
    seen_titles = set()
    try:
        resp = requests.get("https://tubitak.gov.tr/tr", headers=HEADERS, timeout=(5, 10), verify=False)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if 25 < len(title) < 250 and ("duyuru" in href.lower() or "cagri" in href.lower()):
                norm = tr_lower(title)
                if norm not in seen_titles:
                    seen_titles.add(norm)
                    full_link = href if href.startswith("http") else f"https://tubitak.gov.tr/{href.lstrip('/')}"
                    items.append(("TÜBİTAK", title, full_link))
        log(f"   -> TÜBİTAK tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> TÜBİTAK atlandı: {e}")
    return items

def scrape_epdk():
    log("6/7 EPDK (Daraltılmış Odak) taranıyor...")
    items = []
    seen_titles = set()
    try:
        resp = requests.get("https://www.epdk.gov.tr/Detay/Icerik/3-0-0/duyurular", headers=HEADERS, timeout=(5, 10), verify=False)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if 25 < len(title) < 220 and "Detay/Icerik" in href:
                norm_title = tr_lower(title)
                if norm_title not in seen_titles:
                    seen_titles.add(norm_title)
                    full_link = href if href.startswith("http") else f"https://www.epdk.gov.tr{href}"
                    items.append(("EPDK", title, full_link))
        log(f"   -> EPDK tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> EPDK atlandı: {e}")
    return items

def scrape_kosgeb():
    log("7/7 KOSGEB taranıyor...")
    items = []
    seen_titles = set()
    try:
        resp = requests.get("https://www.kosgeb.gov.tr/site/tr/genel/liste/1/duyurular", headers=HEADERS, timeout=(5, 10), verify=False)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if 25 < len(title) < 220 and ("detay" in href.lower() or "duyuru" in href.lower()):
                norm = tr_lower(title)
                if norm not in seen_titles:
                    seen_titles.add(norm)
                    full_link = href if href.startswith("http") else f"https://www.kosgeb.gov.tr/{href.lstrip('/')}"
                    items.append(("KOSGEB", title, full_link))
        log(f"   -> KOSGEB tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> KOSGEB atlandı: {e}")
    return items

def main():
    seen = load_seen()
    is_first_run = (len(seen) == 0)
    all_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"], ignore_https_errors=True)
        page = context.new_page()
        all_items.extend(scrape_resmi_gazete(page))
        all_items.extend(scrape_gib(page))
        all_items.extend(scrape_sanayi(page))
        browser.close()

    all_items.extend(scrape_turmob())
    all_items.extend(scrape_tubitak())
    all_items.extend(scrape_epdk())
    all_items.extend(scrape_kosgeb())

    log(f"Toplam taranan kayıt: {len(all_items)}")
    new_count = 0

    for source, title, link in all_items:
        item_id = make_id(source, title)
        if item_id in seen:
            continue

        tags = match_categories(source, title)
        if tags:
            if is_first_run and new_count >= 8:
                seen.add(item_id)
                continue

            log(f"Eşleşme [{source}]: {title} -> {tags}")
            if send_telegram(source, title, link, tags):
                seen.add(item_id)
                new_count += 1
        else:
            seen.add(item_id)

    save_seen(seen)
    log(f"İşlem tamamlandı. Gönderilen yeni bildirim: {new_count}")

if __name__ == "__main__":
    main()
