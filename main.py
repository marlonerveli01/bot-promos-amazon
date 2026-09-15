import os
import re
import html
import requests

# --- CONFIGURAÇÕES ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AMAZON_TAG = os.environ.get("AMAZON_TAG", "achadosofe031-20")

HISTORY_FILE = "posted_deals.txt"

# Canais públicos de ofertas monitorados via Telegram Web (sem bloqueio Cloudflare)
MONITORED_CHANNELS = ["gatry", "promobitoficial"]

def load_posted():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def resolve_amazon_url(raw_url, tag):
    """Resolve links encurtados (amzn.to), extrai o ASIN e aplica a sua tag."""
    final_url = raw_url
    try:
        if "amzn.to" in raw_url:
            res = requests.head(raw_url, allow_redirects=True, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            final_url = res.url
    except Exception:
        final_url = raw_url

    # Extrai o código único do produto (ASIN)
    asin_match = re.search(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", final_url)
    if asin_match:
        asin = asin_match.group(1)
        return asin, f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    if "amazon.com.br" in final_url:
        clean_url = final_url.split("?")[0]
        return None, f"{clean_url}?tag={tag}"

    return None, None

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
        return res.status_code == 200
    except Exception as e:
        print(f"Erro ao enviar: {e}")
        return False

def monitor_deals():
    print("Iniciando varredura via Telegram Web Engine...")
    posted_deals = load_posted()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    new_deals = []

    for channel in MONITORED_CHANNELS:
        url = f"https://t.me/s/{channel}"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                print(f"Status {res.status_code} ao ler @{channel}")
                continue
            
            # Divide a página nos blocos de mensagens
            message_blocks = res.text.split('class="tgme_widget_message ')
            print(f"Lidas {len(message_blocks) - 1} postagens de @{channel}")

            for block in message_blocks[1:]:
                # Extrai link da Amazon
                amazon_match = re.search(r'href="([^"]*(?:amazon\.com\.br|amzn\.to)[^"]*)"', block)
                if not amazon_match:
                    continue

                raw_link = amazon_match.group(1).replace("&amp;", "&")
                asin, affiliate_url = resolve_amazon_url(raw_link, AMAZON_TAG)
                if not affiliate_url:
                    continue

                # Identificador único (ASIN do produto ou link)
                deal_id = asin if asin else raw_link
                if deal_id in posted_deals:
                    continue

                # Extrai texto da mensagem
                text_match = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
                if not text_match:
                    continue

                raw_text = text_match.group(1)
                clean_text = re.sub(r'<br\s*/?>', '\n', raw_text)
                clean_text = re.sub(r'<[^>]+>', '', clean_text)
                clean_text = html.unescape(clean_text).strip()

                lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
                title = lines[0] if lines else "Produto em Oferta"

                # Preço e Cupom
                price_match = re.search(r"R\$\s*[\d\.,]+", clean_text)
                price = price_match.group(0) if price_match else ""
                if price and price in title:
                    title = title.replace(price, "").strip()
                title = re.sub(r'[\s\-–|:]+$', '', title).strip()

                coupon = extract_coupon(clean_text)

                new_deals.append({
                    "id": deal_id,
                    "title": title[:140],
                    "price": price,
                    "coupon": coupon,
                    "affiliate_url": affiliate_url
                })

        except Exception as e:
            print(f"Erro ao consultar canal @{channel}: {e}")
            continue

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
