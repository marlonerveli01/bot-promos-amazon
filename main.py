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

# Canais públicos do Telegram que postam links diretos da Amazon Brasil
CHANNELS = [
    "promotop",
    "cmdiasyoutube",
    "escolhasegura",
    "IskandarSouza"
]

def load_posted():
    """Carrega o histórico de itens já postados."""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    """Salva o ID ou ASIN do produto no histórico."""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def resolve_amazon_url(url, tag):
    """Resolve links encurtados (amzn.to / link.amazon), extrai o ASIN e aplica a sua tag."""
    final_url = url
    try:
        # Se for encurtador da Amazon ou genérico, segue o redirecionamento
        if any(domain in url.lower() for domain in ["amzn.to", "link.amazon", "bit.ly"]):
            res = requests.get(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, 
                allow_redirects=True, 
                timeout=10, 
                stream=True
            )
            final_url = res.url
    except Exception as e:
        print(f"Erro ao resolver URL {url}: {e}")
        final_url = url

    # Extrai o código único do produto (ASIN de 10 dígitos)
    asin_match = re.search(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", final_url)
    if asin_match:
        asin = asin_match.group(1)
        return asin, f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    if "amazon.com.br" in final_url:
        clean_url = final_url.split("?")[0]
        return None, f"{clean_url}?tag={tag}"

    return None, None

def extract_coupon(text):
    """Detecta cupons de desconto destacados no texto."""
    match = re.search(r"(?:cupom|código|code)[\s:]+([A-Z0-9_-]{3,20})", text, re.IGNORECASE)
    if match:
        val = match.group(1).upper()
        if val not in ["NOVO", "AQUI", "APP", "DO", "NO", "NA"]:
            return val
    return None

def clean_title(text):
    """Extrai o nome do produto ignorando nomes de outros canais e cabeçalhos."""
    ignore_keywords = [
        "promotop", "escolhasegura", "cmdias", "iskandar", "canaltech", 
        "canal", "grupo", "oferta", "forwarded", "link", "cupom", "r$", "por:"
    ]
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    for line in lines:
        clean = re.sub(r'^[^\w\s]+', '', line).strip()
        lower = clean.lower()
        
        if not clean or len(clean) < 5:
            continue
        if any(kw in lower for kw in ignore_keywords) and len(clean) < 35:
            continue
        if lower.startswith("http"):
            continue
            
        # Remove o preço se estiver na mesma linha do título
        price_match = re.search(r"R\$\s*[\d\.,]+", clean)
        if price_match:
            clean = clean.replace(price_match.group(0), "").strip()
            
        clean = re.sub(r'[\s\-–|:•⚫️]+$', '', clean).strip()
        clean = re.sub(r'^[–\-•⚫️|:]+\s*', '', clean).strip()
        
        if len(clean) >= 6:
            return clean[:130]
            
    return "Produto em Oferta na Amazon"

def send_telegram_deal(deal):
    """Envia a oferta formatada com sua tag para o canal."""
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
            print(f"Falha no envio ao Telegram ({res.status_code}): {res.text}")
            return False
        return True
    except Exception as e:
        print(f"Erro ao conectar com API do Telegram: {e}")
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
                print(f"Canal @{channel} status {res.status_code}")
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            # Localiza todas as postagens pelo atributo oficial data-post do Telegram
            messages = soup.find_all("div", attrs={"data-post": True})
            print(f"Lidas {len(messages)} postagens de @{channel}")

            for msg in messages:
                post_id = msg.get("data-post", "")
                
                text_el = msg.find("div", class_="tgme_widget_message_text")
                raw_text = text_el.get_text(separator="\n").strip() if text_el else ""

                # Encontra todos os links nas tags <a> e também URLs no texto
                links = [a["href"] for a in msg.find_all("a", href=True)]
                text_urls = re.findall(r'https?://[^\s<>"\'()]+', raw_text)
                all_links = list(dict.fromkeys(links + text_urls))

                target_link = None
                for l in all_links:
                    l_lower = l.lower()
                    if any(d in l_lower for d in ["amazon.com.br", "amzn.to", "link.amazon"]):
                        target_link = l
                        break

                if not target_link:
                    continue

                asin, affiliate_url = resolve_amazon_url(target_link, AMAZON_TAG)
                if not affiliate_url:
                    continue

                # Evita postar o mesmo produto repetido
                unique_key = asin if asin else post_id
                if unique_key in posted_deals:
                    continue

                title = clean_title(raw_text)

                price_match = re.search(r"R\$\s*[\d\.,]+", raw_text)
                price = price_match.group(0) if price_match else ""

                coupon = extract_coupon(raw_text)

                new_deals.append({
                    "id": unique_key,
                    "title": title,
                    "price": price,
                    "coupon": coupon,
                    "affiliate_url": affiliate_url
                })

        except Exception as e:
            print(f"Erro em @{channel}: {e}")
            continue

    print(f"Total de ofertas da Amazon identificadas: {len(new_deals)}")

    # Envia até 3 ofertas por execução para manter um fluxo constante e sem spam
    count = 0
    for deal in new_deals[:3]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado com sucesso: {deal['title']}")
            count += 1

    print(f"Ciclo finalizado. {count} novas ofertas enviadas ao seu canal.")

if __name__ == "__main__":
    monitor_deals()
