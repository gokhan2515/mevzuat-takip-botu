import os
import re
import time
import json
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SEEN_FILE = "data/seen_items.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

# Hariç tutulacak PR / Ziyaret / Atama / Sınav kelimeleri
EXCLUDE_KEYWORDS = [
    "ziyaret etti", "ziyareti", "heyet", "çalıştay", "yemin ederek",
    "atama kararları", "atanan", "seçildi", "vefat", "başsağlığı", "kutlama",
    "sınav", "personel alımı", "sözleşmeli personel", "mülakat",
    "staj", "eğitim programı", "sözlüğü", "sempozyum", "zirvesi"
]

# EPDK için özel daraltılmış anahtar kelimeler (Sadece bunlar geçerse bildirilir)
EPDK_KEYWORDS = [
    "yekdem", "biyogaz", "biogas", "çöpgaz", "yenilenebilir enerji", "lng"
]

# Diğer tüm kurumlar için kategori sözlüğü
CATEGORIES = {
    "#KDV_Kurumlar": [
        "kdv", "katma değer vergisi", "kurumlar vergisi", "tevkifat",
        "vergi usul", "indirimli kurumlar", "yatırıma katkı", "enflasyon düzeltmesi",
        "matrah", "istisna", "muafiyet", "stopaj", "beyanname", "sirküler", "vergi tebliği", "gelir idaresi"
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
        "yazılım", "bilişim", "patent", "ticarileşme", "teknokent", "destek çağrısı", "proje çağrısı"
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
    
    # EPDK özel kuralı: Sadece belirlenen 6 kelimeden biri geçiyorsa al
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

def fetch_url(url, encoding=None):
    resp = requests.get(url, headers=HEADERS, timeout=(5, 10), verify=False)
    if encoding:
        resp.encoding = encoding
    return resp.text

def scrape_resmi_gazete():
    log("1/7 Resmî Gazete (Günlük Tam Sayı) taranıyor...")
    items = []
    seen_titles = set()
    now = get_tr_now()
    
    # Doğrudan günün tarihli tam sayı sayfasını ve ana sayfayı kontrol et
    daily_url = f"https://www.resmigazete.gov.tr/eskiler/{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%Y%m%d')}.htm"
    urls_to_try = [daily_url, "https://www.resmigazete.gov.tr/"]

    for target_url in urls_to_try:
        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=(5, 10), verify=False)
            if resp.status_code != 200:
                continue
            # Resmî Gazete arşiv sayfaları bazen windows-1254 veya utf-8 döner
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            
            for a in soup.find_all("a", href=True):
                title = " ".join(a.get_text().split())
                href = a["href"]
                if len(title) > 20 and (".htm" in href.lower() or ".pdf" in href.lower()):
                    norm = tr_lower(title)
                    if norm not in seen_titles and "önceki sayı" not in norm:
                        seen_titles.add(norm)
                        if href.startswith("http"):
                            full_link = href
                        elif href.startswith("/"):
                            full_link = f"https://www.resmigazete.gov.tr{href}"
                        else:
                            base_dir = target_url.rsplit("/", 1)[0]
                            full_link = f"{base_dir}/{href}"
                        items.append(("Resmî Gazete", title, full_link))
            if len(items) > 6:
                break
        except Exception as e:
            log(f"   -> Resmî Gazete denemesi ({target_url}): {e}")

    log(f"   -> Resmî Gazete tamam ({len(items)} kayıt).")
    return items

def scrape_turmob():
    log("2/7 TÜRMOB (Mevzuat Sirküleri) taranıyor...")
    items = []
    seen_titles = set()
    urls = [
        "https://www.turmob.org.tr/Mevzuat/Sirkuler",
        "https://www.turmob.org.tr/Haberler"
    ]
    for url in urls:
        try:
            html = fetch_url(url, "utf-8")
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                title = " ".join(a.get_text().split())
                href = a["href"]
                if 20 < len(title) < 260 and ("sirkuler" in href.lower() or "detay" in href.lower() or "haber" in href.lower()):
                    norm = tr_lower(title)
                    if norm not in seen_titles:
                        seen_titles.add(norm)
                        full_link = href if href.startswith("http") else f"https://www.turmob.org.tr/{href.lstrip('/')}"
                        items.append(("TÜRMOB", title, full_link))
        except Exception:
            continue
    log(f"   -> TÜRMOB tamam ({len(items)} kayıt).")
    return items

def scrape_gib():
    log("3/7 GİB taranıyor...")
    items = []
    seen_titles = set()
    # GİB yeni Next.js API uçlarını ve klasik duyuru sayfalarını dene
    api_endpoints = [
        "https://www.gib.gov.tr/api/duyuru/list?page=0&size=20",
        "https://www.gib.gov.tr/api/mevzuat/list?page=0&size=20"
    ]
    for api_url in api_endpoints:
        try:
            r = requests.get(api_url, headers=HEADERS, timeout=(5, 8), verify=False)
            if r.status_code == 200 and "application/json" in r.headers.get("Content-Type", ""):
                data = r.json()
                records = data.get("content") or data.get("data") or (data if isinstance(data, list) else [])
                for rec in records:
                    title = str(rec.get("baslik") or rec.get("title") or "").strip()
                    slug = str(rec.get("slug") or rec.get("id") or "").strip()
                    if len(title) > 15:
                        norm = tr_lower(title)
                        if norm not in seen_titles:
                            seen_titles.add(norm)
                            link = f"https://www.gib.gov.tr/duyuru/{slug}" if slug else "https://www.gib.gov.tr/duyurular"
                            items.append(("Gelir İdaresi Bşk. (GİB)", title, link))
        except Exception:
            continue

    log(f"   -> GİB tamam ({len(items)} kayıt).")
    return items

def scrape_sanayi():
    log("4/7 Sanayi Bakanlığı taranıyor...")
    items = []
    seen_titles = set()
    endpoints = [
        "https://www.sanayi.gov.tr/medya/duyurular",
        "https://www.sanayi.gov.tr/mevzuat"
    ]
    for ep in endpoints:
        try:
            html = fetch_url(ep, "utf-8")
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                title = " ".join(a.get_text().split())
                href = a["href"]
                if 25 < len(title) < 250 and any(k in href.lower() for k in ["duyuru", "haber", "mevzuat", "detay"]):
                    norm = tr_lower(title)
                    if norm not in seen_titles:
                        seen_titles.add(norm)
                        full_link = href if href.startswith("http") else f"https://www.sanayi.gov.tr/{href.lstrip('/')}"
                        items.append(("Sanayi ve Teknoloji Bak.", title, full_link))
        except Exception:
            continue
    log(f"   -> Sanayi Bak. tamam ({len(items)} kayıt).")
    return items

def scrape_tubitak():
    log("5/7 TÜBİTAK taranıyor...")
    items = []
    seen_titles = set()
    try:
        html = fetch_url("https://tubitak.gov.tr/tr/duyurular", "utf-8")
        soup = BeautifulSoup(html, "html.parser")
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
        html = fetch_url("https://www.epdk.gov.tr/Detay/Icerik/3-0-0/duyurular", "utf-8")
        soup = BeautifulSoup(html, "html.parser")
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
        html = fetch_url("https://www.kosgeb.gov.tr/site/tr/genel/liste/1/duyurular", "utf-8")
        soup = BeautifulSoup(html, "html.parser")
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
    all_items.extend(scrape_resmi_gazete())
    all_items.extend(scrape_turmob())
    all_items.extend(scrape_gib())
    all_items.extend(scrape_sanayi())
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
