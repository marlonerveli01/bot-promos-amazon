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

# Canais públicos monitorados
CHANNELS = [
    "promotop",
    "cmdiasyoutube",
    "escolhasegura",
    "IskandarSouza"
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

def load_posted():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def resolve_amazon_url(url, tag):
    """Expande amzn.to/link.amazon, extrai o ASIN e aplica a sua tag de afiliado."""
    final_url = url
    try:
        if any(domain in url.lower() for domain in ["amzn.to", "link.amazon", "bit.ly"]):
            res = requests.get(url, headers=BROWSER_HEADERS, allow_redirects=True, timeout=8, stream=True)
            final_url = res.url
    except Exception:
        final_url = url

    asin_match = re.search(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", final_url)
    if asin_match:
        asin = asin_match.group(1)
        return asin, f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    if "amazon.com.br" in final_url:
        clean_url = final_url.split("?")[0]
        return None, f"{clean_url}?tag={tag}"

    return None, None

def fetch_amazon_page_details(asin):
    """Consulta diretamente a página do produto na Amazon para ler os blocos de promoção."""
    if not asin:
        return None

    url = f"https://www.amazon.com.br/dp/{asin}"
    try:
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=8)
        if res.status_code != 200 or "validateCaptcha" in res.text:
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        data = {
            "title": "",
            "price": "",
            "payments": [],
            "coupons": [],
            "rules": []
        }

        # 1. Título oficial
        t_el = soup.find(id="productTitle")
        if t_el:
            data["title"] = t_el.get_text().strip()[:130]

        # 2. Preço oficial
        price_el = soup.select_one(".a-price .a-offscreen")
        if price_el:
            data["price"] = price_el.get_text().strip()

        # 3. Cabeçalho da Promoção (Resgatar / Cupons)
        promo_sec = soup.find(id="applicable_promotion_list_sec") or soup.find(class_=re.compile(r"promoPriceBlockMessage", re.I))
        if promo_sec:
            promo_text = re.sub(r'\s+', ' ', promo_sec.get_text()).strip()
            
            # Procura código de cupom no cabeçalho
            c_match = re.search(r'(?:código|cupom|code)[\s:]+([A-Z0-9_-]{3,20})', promo_text, re.IGNORECASE)
            if c_match:
                code = c_match.group(1).upper()
                note = "Resgate na página do produto"
                if "porto" in promo_text.lower():
                    note = "Válido com Cartão Porto Bank Visa"
                elif "prime" in promo_text.lower():
                    note = "Exclusivo membros Prime"
                data["coupons"].append({"code": code, "note": note})
            
            # Adiciona a descrição da promoção às regras
            clean_rule = re.sub(r'Termos|Resgatar', '', promo_text).strip()
            if 10 < len(clean_rule) < 140:
                data["rules"].append(clean_rule)

        # 4. Formas de Pagamento (PIX, NuPay, Parcelamento)
        page_text = res.text
        pix_match = re.search(r'(\d+%\s*off\s*à\s*vista\s*no\s*Pix\s*ou\s*NuPay)', page_text, re.IGNORECASE)
        if pix_match:
            data["payments"].append(pix_match.group(1).strip())
        elif re.search(r'à\s*vista\s*no\s*Pix', page_text, re.IGNORECASE):
            data["payments"].append("À vista no PIX")

        inst_match = re.search(r'(?:em\s+até\s+)?(\d+x\s+(?:de\s+R\$\s*[\d\.,]+\s+)?sem\s+juros)', page_text, re.IGNORECASE)
        if inst_match:
            data["payments"].append(f"Em até {inst_match.group(1).strip()}")

        # Programe e Poupe
        if "programe e poupe" in page_text.lower():
            data["rules"].append("Economize extra ativando o <b>Programe e Poupe</b>")

        return data
    except Exception:
        return None

def parse_telegram_text(text):
    """Extrai informações do texto da postagem de origem (Fallback)."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    text_lower = text.lower()

    # Preço
    price = ""
    for line in lines:
        por_match = re.search(r'(?:por|a\s+partir\s+de)\s*:?\s*(R\$\s*[\d\.,]+)', line, re.IGNORECASE)
        if por_match:
            price = por_match.group(1)
            break
    if not price:
        matches = re.findall(r"R\$\s*[\d\.,]+", text)
        if matches:
            price = matches[-1]

    # Pagamento
    payments = []
    if "nupay" in text_lower:
        payments.append("À vista no PIX ou NuPay")
    elif "pix" in text_lower:
        payments.append("À vista no PIX")
    elif "à vista" in text_lower:
        payments.append("À vista")

    sj_match = re.search(r'(\d+x\s+sem\s+juros)', text_lower)
    if sj_match:
        payments.append(sj_match.group(1))

    # Cupons
    coupons = []
    c_matches = re.findall(r'(?:cupom|c[oó]digo|code)[\s:]+([A-Z0-9_-]{3,20})', text, re.IGNORECASE)
    for c in c_matches:
        c_up = c.upper()
        if c_up not in ["NOVO", "AQUI", "APP", "DO", "NO", "NA", "TELA", "PAGINA", "AMAZON"]:
            note = ""
            if "porto" in text_lower: note = "Cartão Porto Bank Visa"
            elif "prime" in text_lower: note = "Membros Prime"
            coupons.append({"code": c_up, "note": note})

    rules = []
    if "programe e poupe" in text_lower or "recorr" in text_lower:
        rules.append("Economize extra ativando o <b>Programe e Poupe</b>")
    if "finaliza" in text_lower or "carrinho" in text_lower:
        rules.append("Desconto aplicado na finalização da compra")

    return {
        "price": price,
        "payments": payments,
        "coupons": coupons,
        "rules": rules
    }

def clean_title(text):
    ignore_kw = ["promotop", "escolhasegura", "cmdias", "iskandar", "canaltech", "canal", "grupo", "http"]
    for line in [l.strip() for l in text.split('\n') if l.strip()]:
        clean = re.sub(r'^[^\w\s]+', '', line).strip()
        if len(clean) >= 6 and not any(kw in clean.lower() for kw in ignore_kw):
            p = re.search(r"R\$\s*[\d\.,]+", clean)
            if p:
                clean = clean.replace(p.group(0), "").strip()
            clean = re.sub(r'[\s\-–|:•⚫️]+$', '', clean).strip()
            if len(clean) >= 6:
                return clean[:130]
    return "Produto em Oferta na Amazon"

def send_telegram_deal(deal):
    """Monta a postagem completa e transparente para o canal."""
    caption = []
    caption.append("🔥 <b>OFERTA IMPERDÍVEL</b> | 📦 <b>AMAZON</b>\n")
    caption.append(f"📌 <b>{html.escape(deal['title'])}</b>\n")

    if deal.get("price"):
        caption.append(f"💰 <b>Preço:</b> {deal['price']}")

    if deal.get("payments"):
        caption.append(f"💳 <b>Condição:</b> {' | '.join(deal['payments'])}")

    if deal.get("coupons"):
        for c in deal["coupons"]:
            c_str = f"🎟️ <b>Cupom:</b> <code>{c['code']}</code> (toque p/ copiar)"
            if c.get("note"):
                c_str += f"\n   ↳ <i>{c['note']}</i>"
            caption.append(c_str)

    if deal.get("rules"):
        caption.append("\n📝 <b>Como aproveitar o menor valor:</b>")
        for r in deal["rules"][:3]:
            caption.append(f"• {r}")

    caption.append("\n💡 <i>Dica: Ative o cupom ou promoção na página do produto antes de ir ao carrinho!</i>")
    caption.append(f'\n🛒 <a href="{deal["affiliate_url"]}">VER PRODUTO NA AMAZON</a>')

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": "\n".join(caption),
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception:
        return False

def monitor_deals():
    print("Iniciando monitoramento com inspeção direta na Amazon...")
    posted_deals = load_posted()
    new_deals = []

    for channel in CHANNELS:
        url = f"https://t.me/s/{channel}"
        try:
            res = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
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

                # 1. Tenta buscar informações oficiais do cabeçalho da Amazon
                amazon_data = fetch_amazon_page_details(asin)
                
                # 2. Dados do Telegram como fallback ou complemento
                tg_data = parse_telegram_text(raw_text)

                title = (amazon_data and amazon_data["title"]) or clean_title(raw_text)
                price = (amazon_data and amazon_data["price"]) or tg_data["price"]
                payments = (amazon_data and amazon_data["payments"]) or tg_data["payments"]
                coupons = (amazon_data and amazon_data["coupons"]) or tg_data["coupons"]
                rules = list(dict.fromkeys(((amazon_data and amazon_data["rules"]) or []) + tg_data["rules"]))

                new_deals.append({
                    "id": unique_key,
                    "title": title,
                    "price": price,
                    "payments": payments,
                    "coupons": coupons,
                    "rules": rules,
                    "affiliate_url": affiliate_url
                })

        except Exception as e:
            print(f"Erro em @{channel}: {e}")
            continue

    print(f"Total de ofertas identificadas: {len(new_deals)}")

    count = 0
    for deal in new_deals[:3]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado com sucesso: {deal['title']}")
            count += 1

    print(f"Ciclo finalizado. {count} novas ofertas enviadas ao canal.")

if __name__ == "__main__":
    monitor_deals()
