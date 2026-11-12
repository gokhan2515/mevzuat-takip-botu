import os
import json
import hashlib
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import urllib3

# Resmi kurum sitelerindeki SSL sertifika uyarılarını bastır
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SEEN_FILE = "data/seen_items.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

# Kategori bazlı anahtar kelime sözlüğü (Küçük harf duyarlı)
CATEGORIES = {
    "#KDV_Kurumlar": [
        "kdv", "katma değer vergisi", "kurumlar vergisi", "tevkifat",
        "vergi usul", "indirimli kurumlar", "yatırıma katkı", "enflasyon düzeltmesi",
        "matrah", "istisna", "muafiyet", "stopaj", "beyanname", "gelir idaresi"
    ],
    "#Enerji_Tesvik": [
        "enerji", "yekdem", "lisanssız", "elektrik", "güneş enerjisi", "ges",
        "rüzgar enerjisi", "res", "epdk", "yenilenebilir", "depolama",
        "yeşil dönüşüm", "karbon", "enerji verimliliği", "biyokütle", "biyogaz"
    ],
    "#Imalat_Sanayi": [
        "imalat", "sanayi", "yatırım teşvik", "bölgesel teşvik", "öncelikli yatırım",
        "stratejik yatırım", "organize sanayi", "osb", "makine", "teçhizat",
        "ihracat", "yerli malı", "kapasite raporu", "kosgeb", "hamle"
    ],
    "#ArGe_Teknopark": [
        "ar-ge", "arge", "teknopark", "teknoloji geliştirme", "4691", "5746",
        "tübitak", "teydeb", "tasarım merkezi", "inovasyon", "girişim sermayesi",
        "yazılım", "bilişim", "patent", "ticarileşme", "teknokent"
    ]
}

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    # Dosyanın sonsuza dek büyümesini önlemek için son 1500 kaydı tut
    recent_list = list(seen_set)[-1500:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(recent_list, f, ensure_ascii=False, indent=2)

def make_id(source, title):
    raw = f"{source}:{title.strip().lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def match_categories(title):
    text = title.lower()
    matched = []
    for tag, keywords in CATEGORIES.items():
        if any(kw in text for kw in keywords):
            matched.append(tag)
    return matched

def send_telegram(source, title, link, tags):
    if not BOT_TOKEN or not CHAT_ID:
        print("HATA: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik!")
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
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")
        return False

def scrape_resmi_gazete():
    items = []
    try:
        url = "https://www.resmigazete.gov.tr/"
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and (".htm" in href or ".pdf" in href):
                full_link = href if href.startswith("http") else f"https://www.resmigazete.gov.tr/{href.lstrip('/')}"
                items.append(("Resmî Gazete", title, full_link))
    except Exception as e:
        print(f"Resmî Gazete tarama hatası: {e}")
    return items

def scrape_gib():
    items = []
    try:
        url = "https://www.gib.gov.tr/duyurular"
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and "/duyuru" in href:
                full_link = href if href.startswith("http") else f"https://www.gib.gov.tr{href}"
                items.append(("Gelir İdaresi Bşk. (GİB)", title, full_link))
    except Exception as e:
        print(f"GİB tarama hatası: {e}")
    return items

def scrape_sanayi():
    items = []
    try:
        url = "https://www.sanayi.gov.tr/medya/duyurular"
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and ("duyuru" in href or "haber" in href):
                full_link = href if href.startswith("http") else f"https://www.sanayi.gov.tr{href}"
                items.append(("Sanayi ve Teknoloji Bak.", title, full_link))
    except Exception as e:
        print(f"Sanayi Bak. tarama hatası: {e}")
    return items

def scrape_tubitak():
    items = []
    try:
        url = "https://tubitak.gov.tr/tr/duyurular"
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and "/duyuru" in href:
                full_link = href if href.startswith("http") else f"https://tubitak.gov.tr{href}"
                items.append(("TÜBİTAK", title, full_link))
    except Exception as e:
        print(f"TÜBİTAK tarama hatası: {e}")
    return items

def scrape_epdk():
    items = []
    try:
        url = "https://www.epdk.gov.tr/Detay/Icerik/3-0-0/duyurular"
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text().split())
            href = a["href"]
            if len(title) > 25 and ("Detay/Icerik" in href or "duyuru" in href.lower()):
                full_link = href if href.startswith("http") else f"https://www.epdk.gov.tr{href}"
                items.append(("EPDK", title, full_link))
    except Exception as e:
        print(f"EPDK tarama hatası: {e}")
    return items

def main():
    seen = load_seen()
    all_items = []
    
    all_items.extend(scrape_resmi_gazete())
    all_items.extend(scrape_gib())
    all_items.extend(scrape_sanayi())
    all_items.extend(scrape_tubitak())
    all_items.extend(scrape_epdk())

    print(f"Toplam taranan kayıt sayısı: {len(all_items)}")
    new_count = 0

    for source, title, link in all_items:
        item_id = make_id(source, title)
        if item_id in seen:
            continue

        tags = match_categories(title)
        if tags:
            print(f"Eşleşme bulundu [{source}]: {title} -> {tags}")
            if send_telegram(source, title, link, tags):
                seen.add(item_id)
                new_count += 1
        else:
            # İlgisiz başlıkları da tekrar kontrol etmemek için hafızaya al
            seen.add(item_id)

    save_seen(seen)
    print(f"İşlem tamamlandı. Gönderilen yeni bildirim: {new_count}")

if __name__ == "__main__":
    main()
