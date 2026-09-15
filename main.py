import os
import re
import html
import requests
import feedparser

# --- CONFIGURAÇÕES ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AMAZON_TAG = os.environ.get("AMAZON_TAG", "achadosofe031-20")

HISTORY_FILE = "posted_deals.txt"

# Feeds abertos de promoções brasileiras que não barram o GitHub
FEEDS = [
    "https://www.hardmob.com.br/external.php?type=RSS2&forumids=407",
    "https://forum.adrenaline.com.br/forums/promocoes.221/index.rss"
]

def load_posted():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def extract_amazon_info(text, tag):
    """Busca qualquer link da Amazon no texto e formata com sua tag."""
    match = re.search(r'https?://(?:www\.)?amazon\.com\.br/[^\s"\'<>)]+', text)
    if not match:
        return None, None
        
    raw_url = match.group(0)
    
    # Extrai o código único do produto (ASIN)
    asin_match = re.search(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", raw_url)
    if asin_match:
        asin = asin_match.group(1)
        return asin, f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
        
    sep = "&" if "?" in raw_url else "?"
    return raw_url, f"{raw_url}{sep}tag={tag}"

def extract_coupon(text):
    match = re.search(r"(?:cupom|código|code)[\s:]+([A-Z0-9_-]{4,20})", text, re.IGNORECASE)
    return match.group(1).upper() if match else None

def send_telegram_deal(deal):
    coupon_section = f"🎟️ <b>Cupom:</b> <code>{deal['coupon']}</code> (toque p/ copiar)\n" if deal["coupon"] else ""
    price_section = f"💰 <b>Preço:</b> {deal['price']}\n" if deal["price"] else ""

    caption = (
        f"🔥 <b>OFERTA DO DIA</b> | 📦 <b>AMAZON</b>\n\n"
        f"📌 <b>{html.escape(deal['title'])}</b>\n\n"
        f"{price_section}"
        f"{coupon_section}\n"
        f'🛒 <a href="{deal["affiliate_url"]}">VER PRODUTO NA AMAZON</a>'
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"Falha Telegram: {res.status_code} - {res.text}")
            return False
        return True
    except Exception as e:
        print(f"Erro ao enviar para Telegram: {e}")
        return False

def monitor_deals():
    print("Iniciando varredura de ofertas da Amazon...")
    posted_deals = load_posted()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    new_deals = []

    for feed_url in FEEDS:
        try:
            res = requests.get(feed_url, headers=headers, timeout=15)
            if res.status_code != 200:
                print(f"Feed ignorado (status {res.status_code}): {feed_url}")
                continue
                
            feed = feedparser.parse(res.content)
            print(f"Lidos {len(feed.entries)} tópicos de {feed_url}")
        except Exception as e:
            print(f"Erro ao acessar {feed_url}: {e}")
            continue

        for item in feed.entries:
            title = getattr(item, "title", "")
            desc = getattr(item, "description", "")
            guid = getattr(item, "id", getattr(item, "link", ""))

            full_text = f"{title} {desc}"

            # Filtra apenas se mencionar Amazon
            if "amazon" not in full_text.lower():
                continue

            # Extrai link do produto e ASIN
            deal_id, affiliate_url = extract_amazon_info(full_text, AMAZON_TAG)
            if not affiliate_url:
                continue

            unique_key = deal_id if deal_id else guid
            if unique_key in posted_deals:
                continue

            # Limpeza do título (remove tags de fórum como [Amazon])
            clean_title = re.sub(r'\[\s*amazon(?:\.com(?:\.br)?)?\s*\]', '', title, flags=re.IGNORECASE).strip()
            
            # Extração de preço
            price_match = re.search(r"R\$\s*[\d\.,]+", clean_title)
            price = price_match.group(0) if price_match else ""
            if price:
                clean_title = clean_title.replace(price, "").strip()
            clean_title = re.sub(r'[\s\-–|]+$', '', clean_title).strip()

            coupon = extract_coupon(full_text)

            new_deals.append({
                "id": unique_key,
                "title": clean_title,
                "price": price,
                "coupon": coupon,
                "affiliate_url": affiliate_url
            })

    print(f"Ofertas elegíveis encontradas: {len(new_deals)}")

    count = 0
    for deal in new_deals[:3]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado com sucesso: {deal['title']}")
            count += 1

    print(f"Ciclo finalizado. {count} novas ofertas enviadas ao canal.")

if __name__ == "__main__":
    monitor_deals()
