import os
import re
import html
import requests
from bs4 import BeautifulSoup

# --- CONFIGURAÇÕES ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AMAZON_TAG = os.environ.get("AMAZON_TAG", "achadosofe031-20")

HISTORY_FILE = "posted_deals.txt"

# Canais públicos do Telegram ativos com ofertas da Amazon Brasil
CHANNELS = [
    "canaltech_ofertas",
    "gatryofertas",
    "ofertadodia"
]

def load_posted():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def resolve_amazon_url(url, tag):
    """Expande links encurtados (amzn.to), extrai o código ASIN e aplica a sua tag."""
    final_url = url
    try:
        if "amzn.to" in url:
            res = requests.get(
                url, 
                headers={"User-Agent": "Mozilla/5.0"}, 
                allow_redirects=True, 
                timeout=10, 
                stream=True
            )
            final_url = res.url
    except Exception:
        final_url = url

    # Identifica o ASIN do produto
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
    except Exception:
        return False

def monitor_deals():
    print("Iniciando varredura via Telegram Web Engine...")
    posted_deals = load_posted()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    new_deals = []

    for channel in CHANNELS:
        url = f"https://t.me/s/{channel}"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                print(f"Canal @{channel} retornou status {res.status_code}")
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message")
            print(f"Lidas {len(messages)} postagens de @{channel}")

            for msg in messages:
                post_id = msg.get("data-post", "")
                
                # Extrai todo o texto da postagem
                text_el = msg.find("div", class_="tgme_widget_message_text")
                raw_text = text_el.get_text(separator="\n").strip() if text_el else ""

                # Encontra todos os links contidos na mensagem
                links = [a["href"] for a in msg.find_all("a", href=True)]
                
                # Busca também URLs de texto puro (caso não venham em tag <a>)
                text_urls = re.findall(r'https?://[^\s<>"]+', raw_text)
                all_links = list(set(links + text_urls))

                target_link = None
                for l in all_links:
                    if "amazon.com.br" in l or "amzn.to" in l:
                        target_link = l
                        break

                if not target_link:
                    continue

                asin, affiliate_url = resolve_amazon_url(target_link, AMAZON_TAG)
                if not affiliate_url:
                    continue

                unique_key = asin if asin else post_id
                if unique_key in posted_deals:
                    continue

                # Título da primeira linha
                lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
                title = lines[0] if lines else "Produto em Oferta na Amazon"

                # Preço e cupom
                price_match = re.search(r"R\$\s*[\d\.,]+", raw_text)
                price = price_match.group(0) if price_match else ""
                if price and price in title:
                    title = title.replace(price, "").strip()
                title = re.sub(r'[\s\-–|:]+$', '', title).strip()

                coupon = extract_coupon(raw_text)

                new_deals.append({
                    "id": unique_key,
                    "title": title[:140],
                    "price": price,
                    "coupon": coupon,
                    "affiliate_url": affiliate_url
                })

        except Exception as e:
            print(f"Erro em @{channel}: {e}")
            continue

    print(f"Ofertas elegíveis encontradas: {len(new_deals)}")

    # Envia até 3 por execução para evitar bloqueios por flood
    count = 0
    for deal in new_deals[:3]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado com sucesso: {deal['title']}")
            count += 1

    print(f"Ciclo finalizado. {count} novas ofertas enviadas ao canal.")

if __name__ == "__main__":
    monitor_deals()
