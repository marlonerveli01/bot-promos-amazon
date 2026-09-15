import os
import re
import html
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

# --- CONFIGURAÇÕES ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AMAZON_TAG = os.environ.get("AMAZON_TAG")

# Arquivo para não repetir postagens
HISTORY_FILE = "posted_deals.txt"

def load_posted():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def tag_amazon_url(url, tag):
    """Transforma link da Amazon em link de afiliado."""
    # Tenta extrair o ASIN (código do produto)
    asin_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    if asin_match:
        asin = asin_match.group(1)
        return f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    # Se não achar ASIN, só anexa a tag (menos garantido, mas funciona)
    if "?" in url:
        return f"{url}&tag={tag}"
    return f"{url}?tag={tag}"

def extract_coupon(text):
    """Tenta achar códigos de cupom no texto."""
    match = re.search(r"(?:cupom|código|code)[\s:]+([A-Z0-9_-]{4,20})", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None

def send_telegram_deal(deal):
    """Envia a formatação final para o Telegram."""
    
    coupon_section = f"🎟️ <b>Cupom:</b> <code>{deal['coupon']}</code> (Toque p/ copiar)\n" if deal["coupon"] else ""
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
        "parse_mode": "HTML"
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except:
        return False

def monitor_deals():
    print("Iniciando monitoramento da Amazon...")
    posted_deals = load_posted()
    
    # Fonte de ofertas (Gatry é ótimo para o Brasil)
    feed_url = "https://gatry.com/feed"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        res = requests.get(feed_url, headers=headers, timeout=15)
        root = ET.fromstring(res.content)
    except Exception as e:
        print(f"Erro ao ler feed: {e}")
        return

    items = root.findall(".//item")
    count = 0

    # Processa os itens do mais antigo para o mais novo
    for item in reversed(items):
        title = item.find("title").text if item.find("title") is not None else ""
        link = item.find("link").text if item.find("link") is not None else ""
        guid = item.find("guid").text if item.find("guid") is not None else link
        desc = item.find("description").text if item.find("description") is not None else ""

        # SÓ PROCESSA SE FOR AMAZON E NÃO FOI POSTADO
        if guid in posted_deals or "amazon.com" not in link:
            continue

        # Pega o preço se tiver no título
        price_match = re.search(r"R\$\s*[\d\.,]+", title)
        price = price_match.group(0) if price_match else ""
        
        # Tenta achar cupom
        coupon = extract_coupon(title + " " + desc)

        # Cria o link de afiliado
        affiliate_url = tag_amazon_url(link, AMAZON_TAG)

        deal = {
            "id": guid,
            "title": title.replace(price, "").strip(), # Remove preço do título p/ não repetir
            "price": price,
            "coupon": coupon,
            "affiliate_url": affiliate_url
        }

        # Envia e salva no histórico
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado: {deal['title']}")
            count += 1
        
        # Limite de 3 posts por vez para não dar spam
        if count >= 3:
            break

    print(f"Finalizado. {count} novas ofertas.")

if __name__ == "__main__":
    monitor_deals()
