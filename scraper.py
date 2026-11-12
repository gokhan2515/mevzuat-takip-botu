import os
import json
import hashlib
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SEEN_FILE = "data/seen_items.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

EXCLUDE_KEYWORDS = [
    "ziyaret etti", "ziyareti", "heyet", "çalıştay", "yemin ederek",
    "atama kararları", "atanan", "seçildi", "vefat", "başsağlığı", "kutlama",
    "sınav", "personel alımı", "sözleşmeli personel", "mülakat",
    "staj", "eğitim programı", "sözlüğü", "sempozyum", "zirvesi", "boru gazı ithalat"
]

CATEGORIES = {
    "#KDV_Kurumlar": [
        "kdv", "katma değer vergisi", "kurumlar vergisi", "tevkifat",
        "vergi usul", "indirimli kurumlar", "yatırıma katkı", "enflasyon düzeltmesi",
        "matrah", "istisna", "muafiyet", "stopaj", "beyanname", "sirküler", "tebliğ"
    ],
    "#Enerji_Tesvik": [
        "yekdem", "lisanssız", "güneş enerjisi", "ges", "rüzgar enerjisi", "res",
        "yenilenebilir enerji", "depolamalı", "depolama tesisi", "yeşil dönüşüm",
        "karbon", "enerji verimliliği", "biyokütle", "biyogaz", "tarife tabloları",
        "dağıtım sisteminin kullanımına", "elektrik piyasası"
    ],
    "#Imalat_Sanayi": [
        "imalat", "yatırım teşvik", "bölgesel teşvik", "öncelikli yatırım",
        "stratejik yatırım", "organize sanayi", "osb", "makine ve teçhizat",
        "ihracat", "yerli malı", "kapasite raporu", "kosgeb", "hamle", "sanayi sicil"
    ],
    "#ArGe_Teknopark": [
        "ar-ge", "arge", "teknopark", "teknoloji geliştirme", "4691", "5746",
        "tübitak", "teydeb", "tasarım merkezi", "inovasyon", "girişim sermayesi",
        "yazılım", "bilişim", "patent", "ticarileşme", "teknokent", "destek çağrı", "proje çağrı"
    ]
}

def log(msg):
    print(msg, flush=True)

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    recent_list = list(seen_set)[-2000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(recent_list, f, ensure_ascii=False, indent=2)

def make_id(source, title):
    raw = f"{source}:{title[:80].strip().lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def match_categories(title):
    text = title.lower()
    if any(bad in text for bad in EXCLUDE_KEYWORDS):
        return []
    return [tag for tag, kws in CATEGORIES.items() if any(kw in text for kw in kws)]

def send_telegram(source, title, link, tags):
    if not BOT_TOKEN or not CHAT_ID:
        log("KRİTİK HATA: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik!")
        return False

    tag_str = " ".join(tags)
    today_str = datetime.now().strftime("%d.%m.%Y")
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
            return True
        log(f"TELEGRAM HATA ({r.status_code}): {r.text}")
        return False
    except Exception as e:
        log(f"Telegram bağlantı hatası: {e}")
        return False

def fetch_url(url, encoding=None):
    resp = requests.get(url, headers=HEADERS, timeout=(5, 8), verify=False)
    if encoding:
        resp.encoding = encoding
    return resp.text

def scrape_resmi_gazete():
    log("1/5 Resmî Gazete taranıyor...")
    items = []
    try:
        html = fetch_url("https://www.resmigazete.gov.tr/", "utf-8")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and (".htm" in href or ".pdf" in href):
                full_link = href if href.startswith("http") else f"https://www.resmigazete.gov.tr/{href.lstrip('/')}"
                items.append(("Resmî Gazete", title, full_link))
        log(f"   -> Resmî Gazete tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> Resmî Gazete atlandı: {e}")
    return items

def scrape_gib():
    log("2/5 GİB taranıyor...")
    items = []
    try:
        html = fetch_url("https://www.gib.gov.tr/")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and len(title) < 250 and ("duyuru" in href.lower() or "sirkuler" in href.lower() or "teblig" in href.lower()):
                full_link = href if href.startswith("http") else f"https://www.gib.gov.tr/{href.lstrip('/')}"
                items.append(("Gelir İdaresi Bşk. (GİB)", title, full_link))
        log(f"   -> GİB tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> GİB atlandı: {e}")
    return items

def scrape_sanayi():
    log("3/5 Sanayi Bakanlığı taranıyor...")
    items = []
    try:
        html = fetch_url("https://www.sanayi.gov.tr/")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and len(title) < 250 and ("duyuru" in href.lower() or "haber" in href.lower()):
                full_link = href if href.startswith("http") else f"https://www.sanayi.gov.tr/{href.lstrip('/')}"
                items.append(("Sanayi ve Teknoloji Bak.", title, full_link))
        log(f"   -> Sanayi Bak. tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> Sanayi Bak. atlandı: {e}")
    return items

def scrape_tubitak():
    log("4/5 TÜBİTAK taranıyor...")
    items = []
    try:
        html = fetch_url("https://tubitak.gov.tr/tr")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and len(title) < 250 and ("duyuru" in href.lower() or "cagri" in href.lower()):
                full_link = href if href.startswith("http") else f"https://tubitak.gov.tr/{href.lstrip('/')}"
                items.append(("TÜBİTAK", title, full_link))
        log(f"   -> TÜBİTAK tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> TÜBİTAK atlandı: {e}")
    return items

def scrape_epdk():
    log("5/5 EPDK taranıyor...")
    items = []
    seen_titles = set()
    try:
        html = fetch_url("https://www.epdk.gov.tr/Detay/Icerik/3-0-0/duyurular")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and len(title) < 220 and "Detay/Icerik" in href:
                norm_title = title.lower()
                if norm_title not in seen_titles:
                    seen_titles.add(norm_title)
                    full_link = href if href.startswith("http") else f"https://www.epdk.gov.tr{href}"
                    items.append(("EPDK", title, full_link))
        log(f"   -> EPDK tamam ({len(items)} kayıt).")
    except Exception as e:
        log(f"   -> EPDK atlandı: {e}")
    return items

def main():
    seen = load_seen()
    is_first_run = (len(seen) == 0)
    
    all_items = []
    all_items.extend(scrape_resmi_gazete())
    all_items.extend(scrape_gib())
    all_items.extend(scrape_sanayi())
    all_items.extend(scrape_tubitak())
    all_items.extend(scrape_epdk())

    log(f"Toplam taranan kayıt: {len(all_items)}")
    new_count = 0

    for source, title, link in all_items:
        item_id = make_id(source, title)
        if item_id in seen:
            continue

        tags = match_categories(title)
        if tags:
            if is_first_run and new_count >= 5:
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
