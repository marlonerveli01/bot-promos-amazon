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

# Canais públicos do Telegram que postam ofertas diárias da Amazon Brasil
CHANNELS = [
    "promotop",
    "cmdiasyoutube",
    "escolhasegura",
    "IskandarSouza"
]

def load_posted():
    """Carrega histórico de produtos já postados para evitar repetições."""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted(deal_id):
    """Salva o ID ou ASIN do produto no histórico."""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{deal_id}\n")

def resolve_amazon_url(url, tag):
    """Expande links encurtados (amzn.to), extrai o código ASIN e aplica a sua tag."""
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
        print(f"Erro ao resolver URL {url}: {e}")
        final_url = url

    # Identifica o ASIN de 10 dígitos do produto
    asin_match = re.search(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})", final_url)
    if asin_match:
        asin = asin_match.group(1)
        return asin, f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
    
    if "amazon.com.br" in final_url:
        clean_url = final_url.split("?")[0]
        return None, f"{clean_url}?tag={tag}"

    return None, None

def clean_title(text):
    """Extrai o título limpo do produto ignorando nomes de outros canais."""
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
            
        # Remove preços do título se houver
        p_match = re.search(r"R\$\s*[\d\.,]+", clean)
        if p_match:
            clean = clean.replace(p_match.group(0), "").strip()
            
        clean = re.sub(r'[\s\-–|:•⚫️]+$', '', clean).strip()
        clean = re.sub(r'^[–\-•⚫️|:]+\s*', '', clean).strip()
        
        if len(clean) >= 6:
            return clean[:130]
            
    return "Produto em Oferta na Amazon"

def parse_deal_details(text):
    """Analisa o texto da postagem para extrair preço, forma de pagamento, cupons e regras."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    text_lower = text.lower()

    # 1. Extração do Preço Promocional (prioriza valor após 'por' ou o último listado)
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

    # 2. Detecção de Cupons e Restrições (Ex: Porto Bank, NuPay, Visa)
    coupon = None
    coupon_note = ""
    for line in lines:
        c_match = re.search(r"(?:cupom|código|code)[\s:]+([A-Z0-9_-]{3,20})", line, re.IGNORECASE)
        if c_match:
            cand = c_match.group(1).upper()
            if cand not in ["NOVO", "AQUI", "APP", "DO", "NO", "NA", "TELA", "PAGINA", "AMAZON", "FRETE", "COMPRE"]:
                coupon = cand
                l_cand = line.lower()
                if "porto" in l_cand:
                    coupon_note = "Cartão Porto Bank Visa"
                elif "nupay" in l_cand or "nubank" in l_cand:
                    coupon_note = "NuPay / Nubank"
                elif "prime" in l_cand:
                    coupon_note = "Membros Amazon Prime"
                elif "app" in l_cand:
                    coupon_note = "Exclusivo no App Amazon"
                elif "visa" in l_cand:
                    coupon_note = "Cartão Visa"
                elif "mastercard" in l_cand:
                    coupon_note = "Cartão Mastercard"
                break

    # 3. Forma de Pagamento (PIX, Boleto, Cartões específicos)
    pay_methods = []
    if "pix" in text_lower:
        pay_methods.append("À vista no PIX")
    elif "boleto" in text_lower:
        pay_methods.append("Boleto bancário")
    elif "à vista" in text_lower or "a vista" in text_lower:
        pay_methods.append("À vista")

    # Adiciona menção a cartão específico se não estiver no cupom
    if ("porto bank" in text_lower or "porto seguro" in text_lower) and "porto" not in coupon_note.lower():
        pay_methods.append("Cartão Porto Bank Visa")
    elif ("nupay" in text_lower or "nubank" in text_lower) and "nupay" not in coupon_note.lower():
        pay_methods.append("NuPay")

    sj_match = re.search(r"(\d+x\s+sem\s+juros)", text_lower)
    if sj_match:
        pay_methods.append(sj_match.group(1))

    payment_info = " ou ".join(pay_methods) if pay_methods else None

    # 4. Regras e Condições para Chegar no Menor Valor
    rules = []
    if "programe e poupe" in text_lower or "recorr" in text_lower:
        rules.append("Economize ainda mais selecionando <b>Programe e Poupe</b>")
        
    if any(k in text_lower for k in ["na tela", "na página", "resgate", "resgatar", "marque", "destaque"]):
        rules.append("Ative/resgate o cupom de desconto na página do produto")
        
    if "finaliza" in text_lower or "carrinho" in text_lower or "checkout" in text_lower:
        rules.append("Desconto aplicado na finalização da compra (no carrinho)")
        
    if ("prime" in text_lower and any(w in text_lower for w in ["exclusivo", "membro", "assinante"])) and "prime" not in coupon_note.lower():
        rules.append("Oferta ou desconto exclusivo para membros <b>Amazon Prime</b>")

    if "mais por menos" in text_lower or any(k in text_lower for k in ["compre 2", "compre 3", "compre 5"]):
        rules.append("Desconto progressivo cumulativo na compra de mais unidades")

    return {
        "price": price_str,
        "payment": payment_info,
        "coupon": coupon,
        "coupon_note": coupon_note,
        "rules": rules
    }

def send_telegram_deal(deal):
    """Envia a oferta formatada com detalhes completos de compra."""
    caption = []
    caption.append("🔥 <b>OFERTA DO DIA</b> | 📦 <b>AMAZON</b>\n")
    caption.append(f"📌 <b>{html.escape(deal['title'])}</b>\n")

    if deal.get("price"):
        caption.append(f"💰 <b>Preço:</b> {deal['price']}")

    if deal.get("payment"):
        caption.append(f"💳 <b>Pagamento:</b> {deal['payment']}")

    if deal.get("coupon"):
        c_str = f"🎟️ <b>Cupom:</b> <code>{deal['coupon']}</code> (toque p/ copiar)"
        if deal.get("coupon_note"):
            c_str += f"\n   ↳ <i>Válido com {deal['coupon_note']}</i>"
        caption.append(c_str)

    if deal.get("rules"):
        caption.append("\n📝 <b>Como chegar no menor valor:</b>")
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
    print("Iniciando varredura com extração detalhada de condições...")
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
                    "payment": details["payment"],
                    "coupon": details["coupon"],
                    "coupon_note": details["coupon_note"],
                    "rules": details["rules"],
                    "affiliate_url": affiliate_url
                })

        except Exception as e:
            print(f"Erro ao processar canal @{channel}: {e}")
            continue

    print(f"Total de ofertas identificadas: {len(new_deals)}")

    # Envia até 3 novidades por ciclo
    count = 0
    for deal in new_deals[:3]:
        if send_telegram_deal(deal):
            save_posted(deal["id"])
            print(f"Postado com sucesso: {deal['title']}")
            count += 1

    print(f"Ciclo finalizado. {count} novas ofertas enviadas ao canal.")

if __name__ == "__main__":
    monitor_deals()
