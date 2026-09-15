import os
import re
import html
import requests
import feedparser # Biblioteca tolerante para ler feeds
from urllib.parse import urlparse

# --- CONFIGURAÇÕES DO TELEGRAM E AFILIADO ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AMAZON_TAG = os.environ.get("AMAZON_TAG", "achadosofe031-20") # Sua tag oficial

# Arquivo para salvar o histórico e não repetir postagens
HISTORY_FILE = "posted_deals.txt"

def load_posted():
    """Carrega o histórico de IDs já postados."""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    """Salva um novo ID no histórico."""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def tag_amazon_url(url, tag):
    """Transforma qualquer link da Amazon em link com sua tag de comissão."""
    # Tenta extrair o ASIN (código único do produto Amazon)
    asin_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    if asin_match:
        asin = asin_match.group(1)
        # Cria a URL limpa e oficial com a tag
        return f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    # Caso seja outro formato de link da Amazon, anexa o parâmetro tag
    if "?" in url:
        return f"{url}&tag={tag}"
    return f"{url}?tag={tag}"

def extract_coupon(text):
    """Detecta padrões comuns de códigos de cupons no texto."""
    match = re.search(r"(?:cupom|código|code)[\s:]+([A-Z0-9_-]{4,20})", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None

def send_telegram_deal(deal):
    """Publica a oferta com formatação visual atraente em HTML."""
    
    coupon_section = f"🎟️ <b>Cupom:</b> <code>{deal['coupon']}</code> (Toque p/ copiar)\n" if deal["coupon"] else ""
    price_section = f"💰 <b>Preço:</b> {deal['price']}\n" if deal["price"] else ""

    caption = (
        f"🔥 <b>OFERTA IMPERDÍVEL</b> | 📦 <b>AMAZON</b>\n\n"
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
        # disable_web_page_preview: False permite mostrar imagem do produto no Telegram
        "disable_web_page_preview": False
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"Erro ao enviar para o Telegram: {e}")
        return False

def monitor_deals():
    """Lógica principal de monitoramento e postagem."""
    print("Iniciando monitoramento da Amazon via Pelando...")
    posted_deals = load_posted()
    
    # --- NOVA FONTE ESTÁVEL (Pelando - Ofertas Quentes) ---
    feed_url = "https://www.pelando.com.br/api/rss/hot"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(feed_url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"Erro ao ler feed: status {res.status_code}")
            return
            
        # feedparser lida bem com XML mal formatado
        feed = feedparser.parse(res.content)
        
    except Exception as e:
        print(f"Falha ao conectar no feed: {e}")
        return

    # No feedparser, acessamos os itens com feed.entries
    items = feed.entries
    new_deals = []

    # Processa os itens na ordem do feed
    for item in items:
        title = item.title if hasattr(item, 'title') else ""
        link = item.link if hasattr(item, 'link') else ""
        # guid vira 'id' no feedparser
        guid = item.id if hasattr(item, 'id') else link
        desc = item.description if hasattr(item, 'description') else ""

        # --- TRAVA DE SEGURANÇA: SÓ PROCESSA AMAZON E NÃO POSTADOS ---
        if guid in posted_deals or "amazon.com" not in link:
            continue

        # Identifica o preço se tiver no título
        price_match = re.search(r"R\$\s*[\d\.,]+", title)
        price = price_match.group(0) if price_match else ""
        
        # Identifica cupom se houver
        coupon = extract_coupon(title + " " + desc)

        # Cria a URL final de afiliado com sua tag
        affiliate_url = tag_amazon_url(link, AMAZON_TAG)

        new_deals.append({
            "id": guid,
            "title": title.replace(price, "").strip(), # Título limpo
            "price": price,
            "coupon": coupon,
            "affiliate_url": affiliate_url
        })

    # Envia as novidades (limite de 3 por execução para não dar spam)
    count = 0
    for deal in new_deals[:3]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Oferta enviada: {deal['title']}")
            count += 1

    print(f"Ciclo finalizado. {count} novas ofertas da Amazon enviadas.")

if __name__ == "__main__":
    monitor_deals()
