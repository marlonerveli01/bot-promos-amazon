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

# Canais públicos de promoções da Amazon Brasil
CHANNELS = [
    "promotop",
    "cmdiasyoutube",
    "escolhasegura",
    "IskandarSouza"
]

def load_posted():
    """Carrega o histórico de itens já postados para não repetir ofertas."""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    """Registra o item no histórico."""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def resolve_amazon_url(url, tag):
    """Expande links amzn.to/link.amazon, extrai o ASIN e aplica a sua tag."""
    final_url = url
    try:
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
        print(f"Erro ao resolver URL: {e}")
        final_url = url

    asin_match = re.search(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", final_url)
    if asin_match:
        asin = asin_match.group(1)
        return asin, f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    if "amazon.com.br" in final_url:
        clean_url = final_url.split("?")[0]
        return None, f"{clean_url}?tag={tag}"

    return None, None

def clean_title(text):
    """Extrai o título limpo do produto ignorando nomes de canais."""
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
            
        # Remove preços do título
        p_match = re.search(r"R\$\s*[\d\.,]+", clean)
        if p_match:
            clean = clean.replace(p_match.group(0), "").strip()
            
        clean = re.sub(r'[\s\-–|:•⚫️]+$', '', clean).strip()
        clean = re.sub(r'^[–\-•⚫️|:]+\s*', '', clean).strip()
        
        if len(clean) >= 6:
            return clean[:130]
            
    return "Produto em Oferta na Amazon"

def parse_deal_details(text):
    """Analisa o texto completo e extrai preço, desconto %, pagamento, cupons e regras."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    text_lower = text.lower()

    # 1. Preço promocional (procura o valor final ou após 'por')
    price_str = ""
    for line in lines:
        por_match = re.search(r'(?:por|a\s+partir\s+de)\s*:?\s*(R\$\s*[\d\.,]+)', line, re.IGNORECASE)
        if por_match:
            price_str = por_match.group(1)
            break
    if not price_str:
        for line in lines:
            if re.match(r'^\s*de\s+R\$', line, re.IGNORECASE) and not re.search(r'por\s+R\$', line, re.IGNORECASE):
                continue
            matches = re.findall(r"R\$\s*[\d\.,]+", line)
            if matches:
                price_str = matches[-1]
                break

    # 2. Desconto em porcentagem (ex: 10% off, 15% de desconto, -35%)
    discount_pct = ""
    pct_match = re.search(r'(?:-\s*)?(\d{1,2}%\s*(?:off|de\s+desconto)?)', text, re.IGNORECASE)
    if pct_match and "%" in pct_match.group(1):
        discount_pct = pct_match.group(1).strip()

    # 3. Formas de Pagamento
    payments = []
    if re.search(r'(?:à\s*vista|a\s*vista)\s+no\s+cart[aã]o', text_lower):
        payments.append("À vista no Cartão de Crédito")
    elif "pix" in text_lower:
        payments.append("À vista no PIX")
    elif "boleto" in text_lower:
        payments.append("Boleto bancário")
    elif "à vista" in text_lower or "a vista" in text_lower:
        payments.append("À vista")

    # Cartões específicos
    if "porto bank" in text_lower or "porto seguro" in text_lower:
        payments.append("Cartão Porto Bank Visa")
    elif "nupay" in text_lower or "nubank" in text_lower:
        payments.append("NuPay / Nubank")

    # Parcelamento sem juros
    parcelas_m = re.search(r'(\d+x\s+(?:de\s+R\$\s*[\d\.,]+\s+)?sem\s+juros)', text_lower)
    if parcelas_m:
        payments.append(f"Em até {parcelas_m.group(1)}")
    elif re.search(r'sem\s+juros', text_lower) and "sem juros" not in " ".join(payments).lower():
        payments.append("Parcelamento sem juros")

    # 4. Cupons e Códigos de Desconto
    coupons = []
    c_matches = re.findall(r'(?:cupom|c[oó]digo|code)[\s:]+([A-Z0-9_-]{3,20})', text, re.IGNORECASE)
    for c in c_matches:
        c_up = c.upper()
        if c_up not in ["NOVO", "AQUI", "APP", "DO", "NO", "NA", "TELA", "PAGINA", "AMAZON", "FRETE", "COMPRE", "PARA", "COM"]:
            note = ""
            for line in lines:
                if c_up in line.upper():
                    l_low = line.lower()
                    if "porto" in l_low: note = "Válido com Cartão Porto Bank"
                    elif "prime" in l_low: note = "Exclusivo membros Prime"
                    elif "nupay" in l_low: note = "Via NuPay"
                    elif "app" in l_low: note = "Apenas no App Amazon"
                    elif "visa" in l_low: note = "Cartões Visa"
                    break
            coupons.append({"code": c_up, "note": note})

    # 5. Regras e Condições para Chegar no Menor Valor
    rules = []
    if "programe e poupe" in text_lower or "recorr" in text_lower:
        rules.append("Economize ainda mais selecionando <b>Programe e Poupe</b>")
        
    if any(k in text_lower for k in ["na tela", "na página", "resgate", "resgatar", "marque", "destaque"]):
        rules.append("Ative/resgate o cupom de desconto na página do produto")
        
    if "finaliza" in text_lower or "carrinho" in text_lower or "checkout" in text_lower:
        rules.append("Desconto aplicado na finalização da compra (no carrinho)")
        
    if re.search(r'pr[eé]-venda', text_lower):
        rules.append("Produto em <b>Pré-venda</b> com menor preço garantido")

    if ("prime" in text_lower and any(w in text_lower for w in ["exclusivo", "membro", "assinante"])) and not any("prime" in c.get('note', '').lower() for c in coupons):
        rules.append("Condição ou desconto exclusivo para membros <b>Amazon Prime</b>")

    if "mais por menos" in text_lower or any(k in text_lower for k in ["compre 2", "compre 3", "compre 5"]):
        rules.append("Desconto progressivo cumulativo na compra de mais unidades")

    return {
        "price": price_str,
        "discount_pct": discount_pct,
        "payments": payments,
        "coupons": coupons,
        "rules": rules
    }

def send_telegram_deal(deal):
    """Envia a oferta formatada com as informações completas de pagamento e cupom."""
    caption = []
    caption.append("🔥 <b>OFERTA IMPERDÍVEL</b> | 📦 <b>AMAZON</b>\n")
    caption.append(f"📌 <b>{html.escape(deal['title'])}</b>\n")

    # Linha de Preço com Porcentagem de Desconto
    price_line = f"💰 <b>Preço:</b> {deal['price']}" if deal.get("price") else ""
    if deal.get("discount_pct") and price_line:
        price_line += f" <i>({deal['discount_pct']})</i>"
    if price_line:
        caption.append(price_line)

    # Linha de Condição / Forma de Pagamento
    if deal.get("payments"):
        pay_str = " | ".join(deal["payments"])
        caption.append(f"💳 <b>Condição:</b> {pay_str}")

    # Cupons
    if deal.get("coupons"):
        for c in deal["coupons"]:
            c_text = f"🎟️ <b>Cupom:</b> <code>{c['code']}</code> (toque p/ copiar)"
            if c.get("note"):
                c_text += f"\n   ↳ <i>{c['note']}</i>"
            caption.append(c_text)

    # Regras e Detalhes
    if deal.get("rules"):
        caption.append("\n📝 <b>Como aproveitar o menor valor:</b>")
        for r in deal["rules"][:4]:
            caption.append(f"• {r}")

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
        if res.status_code != 200:
            print(f"Falha ao enviar ao Telegram ({res.status_code}): {res.text}")
            return False
        return True
    except Exception as e:
        print(f"Erro ao conectar no Telegram: {e}")
        return False

def monitor_deals():
    print("Iniciando varredura com captura avançada de cupons, pagamentos e descontos...")
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
                    l_lower = l.lower()
                    if any(d in l_lower for d in ["amazon.com.br", "amzn.to", "link.amazon"]):
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
                details = parse_deal_details(raw_text)

                new_deals.append({
                    "id": unique_key,
                    "title": title,
                    "price": details["price"],
                    "discount_pct": details["discount_pct"],
                    "payments": details["payments"],
                    "coupons": details["coupons"],
                    "rules": details["rules"],
                    "affiliate_url": affiliate_url
                })

        except Exception as e:
            print(f"Erro no canal @{channel}: {e}")
            continue

    print(f"Total de ofertas elegíveis: {len(new_deals)}")

    count = 0
    for deal in new_deals[:3]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado com sucesso: {deal['title']}")
            count += 1

    print(f"Ciclo finalizado. {count} novas ofertas enviadas ao canal.")

if __name__ == "__main__":
    monitor_deals()
