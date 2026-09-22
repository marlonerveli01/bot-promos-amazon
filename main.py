import os
import re
import html
import time
import requests
from bs4 import BeautifulSoup

# --- CONFIGURAÇÕES ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
AMAZON_TAG = os.environ.get("AMAZON_TAG", "achadosofe031-20")

HISTORY_FILE = "posted_deals.txt"

# Canais públicos de promoções da Amazon
CHANNELS = [
    "promotop",
    "cmdiasyoutube",
    "escolhasegura",
    "IskandarSouza"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def load_posted():
    """Carrega o histórico de itens postados para não repetir."""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    """Salva o ID ou ASIN do produto no histórico."""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def resolve_amazon_url(url, tag):
    """
    Segue os redirecionamentos do link encurtado, extrai o código ASIN
    e monta a URL limpa garantindo a sua tag de afiliado.
    """
    final_url = url
    try:
        if any(domain in url.lower() for domain in ["amzn.to", "link.amazon", "bit.ly"]):
            res = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=8, stream=True)
            final_url = res.url
    except Exception:
        final_url = url

    # Localiza o ASIN de 10 caracteres alfanuméricos da Amazon
    asin_match = re.search(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", final_url)
    if asin_match:
        asin = asin_match.group(1)
        return asin, f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    # Caso seja outro formato de link da Amazon
    if "amazon.com.br" in final_url:
        clean_url = final_url.split("?")[0]
        return None, f"{clean_url}?tag={tag}"

    return None, None

def clean_title(text):
    """Extrai apenas o título do produto sem poluição visual ou nomes de canais."""
    ignore_keywords = [
        "promotop", "escolhasegura", "cmdias", "iskandar", "canaltech", 
        "canal", "grupo", "oferta", "forwarded", "link", "cupom", "http"
    ]
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    for line in lines:
        clean = re.sub(r'^[^\w\s]+', '', line).strip()
        lower = clean.lower()
        
        if not clean or len(clean) < 6:
            continue
        if any(kw in lower for kw in ignore_keywords) and len(clean) < 35:
            continue
        if lower.startswith("http"):
            continue
            
        p_match = re.search(r"R\$\s*[\d\.,]+", clean)
        if p_match:
            clean = clean.replace(p_match.group(0), "").strip()
            
        clean = re.sub(r'[\s\-–|:•⚫️]+$', '', clean).strip()
        clean = re.sub(r'^[–\-•⚫️|:]+\s*', '', clean).strip()
        
        if len(clean) >= 6:
            return clean[:120]
            
    return "Produto em Oferta na Amazon"

def extract_price_and_condition(text):
    """Extrai o preço promocional real e sinaliza se o valor é no Pix ou à vista."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    text_lower = text.lower()
    price_val = ""

    # Prioriza linhas que tenham 'por R$ ...' ou 'a partir de R$ ...'
    for line in lines:
        por_match = re.search(r'(?:por|a\s+partir\s+de)\s*:?\s*(R\$\s*[\d\.,]+)', line, re.IGNORECASE)
        if por_match:
            price_val = por_match.group(1)
            break

    # Fallback: pega o último valor da lista que não seja o preço original ('de R$ ...')
    if not price_val:
        for line in lines:
            if re.match(r'^\s*de\s+R\$', line, re.IGNORECASE) and not re.search(r'por\s+R\$', line, re.IGNORECASE):
                continue
            matches = re.findall(r"R\$\s*[\d\.,]+", line)
            if matches:
                price_val = matches[-1]

    if not price_val:
        return ""

    # Identifica se a condição é no Pix ou à vista
    condition = ""
    if "pix" in text_lower:
        condition = " (no Pix)"
    elif "à vista" in text_lower or "a vista" in text_lower:
        condition = " (à vista)"

    return f"{price_val}{condition}"

def extract_coupon(text):
    """Captura apenas códigos de cupons reais e explícitos."""
    match = re.search(r'(?:cupom|código)[\s:]+([A-Z0-9_-]{4,20})', text, re.IGNORECASE)
    if match:
        cand = match.group(1).upper()
        if cand not in ["NOVO", "AQUI", "APP", "AMAZON", "FRETE", "COMPRE", "DESCONTO", "PRIME", "LINK", "PELO"]:
            return cand
    return None

def send_telegram_deal(deal):
    """Monta e dispara a mensagem padronizada no canal."""
    caption = (
        f"🔥 <b>OFERTA DO DIA</b> | 📦 <b>AMAZON</b>\n\n"
        f"📌 <b>{html.escape(deal['title'])}</b>\n\n"
    )

    if deal.get("price"):
        caption += f"💰 <b>Preço:</b> {deal['price']}\n"

    if deal.get("coupon"):
        caption += f"🎟️ <b>Cupom:</b> <code>{deal['coupon']}</code> (toque p/ copiar)\n"

    caption += (
        f'\n🛒 <a href="{deal["affiliate_url"]}">VER PRODUTO NA AMAZON</a>\n\n'
        f"⚠️ <i>Preço e estoque sujeitos a alteração a qualquer momento.</i>"
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
        print(f"Erro no envio ao Telegram: {e}")
        return False

def monitor_deals():
    print("Iniciando varredura limpa e com tag de afiliado blindada...")
    posted_deals = load_posted()
    new_deals = []

    for channel in CHANNELS:
        url = f"https://t.me/s/{channel}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            messages = soup.find_all("div", attrs={"data-post": True})

            for msg in messages:
                post_id = msg.get("data-post", "")
                text_el = msg.find("div", class_="tgme_widget_message_text")
                raw_text = text_el.get_text(separator="\n").strip() if text_el else ""

                links = [a["href"] for a in msg.find_all("a", href=True)]
                text_urls = re.findall(r'https?://[^\s<>"\'()]+', raw_text)
                all_links = list(dict.fromkeys(links + text_urls))

                target_link = None
                for l in all_links:
                    if any(d in l.lower() for d in ["amazon.com.br", "amzn.to", "link.amazon"]):
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

                title = clean_title(raw_text)
                price = extract_price_and_condition(raw_text)
                coupon = extract_coupon(raw_text)

                new_deals.append({
                    "id": unique_key,
                    "title": title,
                    "price": price,
                    "coupon": coupon,
                    "affiliate_url": affiliate_url
                })

        except Exception as e:
            print(f"Erro ao ler @{channel}: {e}")
            continue

    print(f"Total de ofertas válidas encontradas: {len(new_deals)}")

    # Envia até 6 ofertas com pausa de 1.5s entre cada postagem
    count = 0
    for deal in new_deals[:6]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado com sucesso: {deal['title']}")
            count += 1
            time.sleep(1.5)

    print(f"Ciclo finalizado. {count} novas ofertas enviadas ao canal.")

if __name__ == "__main__":
    monitor_deals()
