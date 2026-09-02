import os
import re
import time
import random
import datetime
import smtplib
import threading
import pandas as pd
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from flask import Flask, render_template_string, request, jsonify, send_file

app = Flask(__name__)

# سجلات وحالات النظام
logs = []
scraper_running = False
sender_running = False

ALL_GERMAN_CITIES = [
    "Berlin", "Hamburg", "München", "Köln", "Frankfurt am Main", "Stuttgart", "Düsseldorf", 
    "Dortmund", "Essen", "Leipzig", "Bremen", "Dresden", "Hannover", "Nürnberg", "Duisburg", 
    "Bochum", "Wuppertal", "Bielefeld", "Bonn", "Münster", "Karlsruhe", "Mannheim", "Augsburg", 
    "Wiesbaden", "Gelsenkirchen", "Mönchengladbach", "Braunschweig", "Chemnitz", "Kiel", 
    "Aachen", "Halle", "Magdeburg", "Freiburg", "Krefeld", "Lübeck", "Oberhausen", "Erfurt", 
    "Mainz", "Rostock", "Kassel", "Hagen", "Hamm", "Saarbrücken", "Mülheim an der Ruhr", 
    "Potsdam", "Ludwigshafen", "Oldenburg", "Leverkusen", "Osnabrück", "Solingen", "Heidelberg"
]

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Bewerbung Platform Suite</title>
    <meta name="theme-color" content="#0f172a">
    <style>
        * { box-sizing: border-box; }
        body { font-family: system-ui, -apple-system, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 15px; }
        .container { max-width: 900px; margin: 0 auto; background: #1e293b; padding: 20px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }
        h1 { color: #38bdf8; text-align: center; font-size: 1.5rem; margin-top: 10px; margin-bottom: 20px; }
        
        /* Nav Tabs */
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 2px solid #334155; padding-bottom: 10px; }
        .tab-btn { flex: 1; padding: 12px; background: #334155; color: #94a3b8; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; text-align: center; font-size: 0.95rem; transition: 0.2s; }
        .tab-btn.active { background: #0284c7; color: #fff; }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .section { background: #334155; padding: 18px; margin-bottom: 20px; border-radius: 12px; }
        h2 { margin-top: 0; color: #facc15; font-size: 1.1rem; }
        
        .form-group { margin-bottom: 15px; display: flex; flex-direction: column; gap: 6px; }
        label { font-weight: 600; font-size: 0.88rem; color: #e2e8f0; }
        input[type="text"], input[type="password"], input[type="file"], input[type="number"], select { padding: 12px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #fff; font-size: 0.95rem; width: 100%; }
        
        button.action-btn { padding: 14px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; transition: 0.2s; color: white; width: 100%; font-size: 1rem; margin-top: 10px; }
        .btn-scrape { background: #2563eb; } .btn-scrape:hover { background: #1d4ed8; }
        .btn-send { background: #0284c7; } .btn-send:hover { background: #0369a1; }
        
        #log-box { background: #020617; color: #38bdf8; padding: 12px; height: 300px; overflow-y: auto; font-family: monospace; border-radius: 8px; border: 1px solid #334155; white-space: pre-wrap; line-height: 1.5; font-size: 0.82rem; }
        .hidden { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Bewerbung Automator Suite Pro</h1>

        <!-- الأزرار الرئيسية بين الأقسام -->
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('tab-scrape')">1. الجمع والتعدين 🔍</button>
            <button class="tab-btn" onclick="switchTab('tab-send')">2. الإرسال الذكي ✉️</button>
        </div>

        <!-- 1. قسم الجمع -->
        <div id="tab-scrape" class="tab-content active">
            <div class="section">
                <h2>إعداد خيارات البحث واستخراج الإيمايلات</h2>
                <form id="scrape-form">
                    <div class="form-group">
                        <label>اختر المجال (Niche):</label>
                        <select name="niche_select" id="niche_select" onchange="toggleCustomNiche()">
                            <option value="Pflegedienst">🏥 Pflege & Gesundheit (التمريض والصحة)</option>
                            <option value="Elektriker">⚡ Handwerk & Elektronik (الكهرباء والحرف)</option>
                            <option value="Gastronomie Hotellerie">🏨 Gastronomie & Hotellerie (الفنادق والمطاعم)</option>
                            <option value="IT Softwareentwicklung">💻 IT & Software (تكنولوجيا المعلومات)</option>
                            <option value="Logistik Lager">📦 Logistik & Lager (اللوجستيك)</option>
                            <option value="Mechatroniker Kfz">🔧 Mechatronik & Kfz (الميكانيك)</option>
                            <option value="custom">✏️ مجال آخر (اكتبه يدويًا)...</option>
                        </select>
                    </div>

                    <div class="form-group hidden" id="custom_niche_group">
                        <label>المجال بال ألمانية:</label>
                        <input type="text" name="custom_niche" placeholder="مثال: Dachdecker, Tischler...">
                    </div>

                    <div class="form-group">
                        <label>النطاق الجغرافي:</label>
                        <select name="city_choice">
                            <option value="ALL">🇩🇪 جميع مدن ألمانيا (Alle Städte)</option>
                            <option value="Berlin">Berlin</option>
                            <option value="München">München</option>
                            <option value="Hamburg">Hamburg</option>
                            <option value="Köln">Köln</option>
                            <option value="Frankfurt am Main">Frankfurt am Main</option>
                        </select>
                    </div>

                    <button type="submit" class="action-btn btn-scrape">بدء البحث واستخراج البيانات 🚀</button>
                </form>
            </div>
        </div>

        <!-- 2. قسم الإرسال الذكي -->
        <div id="tab-send" class="tab-content">
            <div class="section">
                <h2>إطلاق الحملات فائقة التخصيص 🧠</h2>
                <form id="send-form" enctype="multipart/form-data">
                    <div class="form-group">
                        <label>Gmail Email:</label>
                        <input type="text" name="email" placeholder="example@gmail.com" required>
                    </div>
                    <div class="form-group">
                        <label>Gmail App Password:</label>
                        <input type="password" name="password" placeholder="xxxx xxxx xxxx xxxx" required>
                    </div>
                    <div class="form-group">
                        <label>ملف البيانات (اختياري - يترك فارغ لاستخدام قاعدة البيانات المجمعة):</label>
                        <input type="file" name="data_file" accept=".xlsx, .csv">
                    </div>
                    <div class="form-group">
                        <label>ملف الـ CV (PDF):</label>
                        <input type="file" name="cv_file" accept=".pdf" required>
                    </div>
                    <div class="form-group">
                        <label>الحد الأقصى للإرسال:</label>
                        <input type="number" name="daily_limit" value="40" min="1" max="100">
                    </div>
                    <button type="submit" class="action-btn btn-send">بدء الحملة الذكية 🚀</button>
                </form>
            </div>
        </div>

        <!-- السجل المباشر -->
        <div class="section">
            <h2>سجل العمليات المباشر (Live Log) 📋</h2>
            <div id="log-box">جاهز للعمل...</div>
        </div>
    </div>

    <script>
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
        }

        function toggleCustomNiche() {
            const select = document.getElementById('niche_select');
            const customGroup = document.getElementById('custom_niche_group');
            if (select.value === 'custom') customGroup.classList.remove('hidden');
            else customGroup.classList.add('hidden');
        }

        setInterval(() => {
            fetch('/get_logs')
                .then(r => r.json())
                .then(data => {
                    const logBox = document.getElementById('log-box');
                    logBox.textContent = data.logs.join('\\n');
                    logBox.scrollTop = logBox.scrollHeight;
                });
        }, 1200);

        document.getElementById('scrape-form').onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            await fetch('/start_scrape', { method: 'POST', body: formData });
        };

        document.getElementById('send-form').onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            await fetch('/start_send', { method: 'POST', body: formData });
        };
    </script>
</body>
</html>
"""

def add_log(text):
    global logs
    logs.append(text)
    if len(logs) > 300:
        logs.pop(0)

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/get_logs')
def get_logs():
    return jsonify({"logs": logs})

# Logic 1: Contact Extraction
def extract_contact_person(text):
    match = re.search(r'(Ansprechpartner(?:in)?|Kontakt|Ihr Ansprechpartner):\s*(Herr|Frau)\s+([A-Z][a-zäöüß]+(?:\s+[A-Z][a-zäöüß]+)?)', text, re.IGNORECASE)
    if match: return match.group(2).strip(), match.group(3).strip()
    match_direct = re.search(r'(Herr|Frau)\s+([A-Z][a-zäöüß]+(?:\s+[A-Z][a-zäöüß]+)?)', text)
    if match_direct: return match_direct.group(1).strip(), match_direct.group(2).strip()
    return "", ""

def extract_company_name(url, soup):
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        parts = re.split(r'[-|–:]', title)
        if len(parts) > 0 and len(parts[0].strip()) < 40:
            return parts[0].strip()
    return ""

def run_scraper_task(niche, city_choice):
    global scraper_running
    scraper_running = True
    cities_to_search = ALL_GERMAN_CITIES if city_choice == "ALL" else [city_choice]
    add_log(f"🔎 بداية البحث فـ المجال: [{niche}] | النطاق: [{city_choice}]...")

    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    total_saved = 0

    for city in cities_to_search:
        add_log(f"📍 فحص مدينة: {city}...")
        search_queries = [f'{niche} {city} Bewerbung E-Mail', f'{niche} {city} Kontakt']
        city_urls = set()
        
        with DDGS() as ddgs:
            for q in search_queries:
                try:
                    for r in ddgs.text(q, max_results=10):
                        if isinstance(r, dict) and 'href' in r: city_urls.add(r['href'])
                except Exception: continue

        city_results = []
        for url in city_urls:
            try:
                res = requests.get(url, headers=headers, timeout=5)
                soup = BeautifulSoup(res.text, 'html.parser')
                company_name = extract_company_name(url, soup)
                salutation, person_name = extract_contact_person(soup.get_text())
                found_emails = set(re.findall(email_regex, res.text))

                for email in found_emails:
                    email_lower = email.lower()
                    if any(email_lower.endswith(ext) for ext in ['.png', '.jpg', '.css', '.js']): continue
                    if any(bad in email_lower for bad in ['example', 'wixpress', 'datenschutz']): continue

                    city_results.append({
                        "Niche": niche, "City": city, "Company": company_name,
                        "Salutation": salutation, "ContactPerson": person_name,
                        "Email": email_lower, "Status": "Pending"
                    })
                    add_log(f"✅ [{city}] تم إيجاد: {email_lower}")
            except Exception: continue

        if city_results:
            df = pd.DataFrame(city_results).drop_duplicates(subset=['Email'])
            file_exists = os.path.exists("emails_database.csv")
            df.to_csv("emails_database.csv", mode='a', index=False, header=not file_exists)
            total_saved += len(df)

    add_log(f"\n🎉 انتهى البحث! تم حفظ: {total_saved} إيميل فـ emails_database.csv.")
    scraper_running = False

@app.route('/start_scrape', methods=['POST'])
def start_scrape():
    global scraper_running
    if scraper_running: return jsonify({"status": "جاري الجمع..."})
    niche_select = request.form.get('niche_select')
    niche = request.form.get('custom_niche', 'Allgemein') if niche_select == 'custom' else niche_select
    city_choice = request.form.get('city_choice', 'ALL')
    threading.Thread(target=run_scraper_task, args=(niche, city_choice)).start()
    return jsonify({"status": "تم البدء"})

# Logic 2: Smart Email Personalization & Sending
def extract_company_from_email(email):
    try:
        domain = email.split('@')[1].lower()
        public_domains = ['gmail.', 'yahoo.', 'hotmail.', 'outlook.', 'gmx.', 'web.']
        if any(pub in domain for pub in public_domains): return "", "allgemein"
        domain_name = domain.split('.')[0].replace('-', ' ').replace('_', ' ')
        company_clean = ' '.join(word.capitalize() for word in domain_name.split())
        return company_clean, "Fachkraft"
    except: return "", "Fachkraft"

def generate_hyper_personalized_email(email, csv_company, csv_niche, city, greeting):
    extracted_company, detected_niche = extract_company_from_email(email)
    company_final = csv_company if (csv_company and csv_company != 'nan') else (f"Firma {extracted_company}" if extracted_company else f"Ihrem Unternehmen in {city}")
    niche_final = csv_niche if (csv_niche and csv_niche != 'nan') else detected_niche

    subjects = [
        f"Initiativbewerbung als {niche_final} - {company_final}",
        f"Bewerbung um eine Stelle als {niche_final} / Standort {city}"
    ]
    selected_subject = random.choice(subjects)

    body = f"""{greeting}

ich verfolge die Arbeit von {company_final} mit großem Interesse. Da Sie im Bereich {niche_final} etabliert sind, möchte ich mich Ihnen gerne als motivierte Fachkraft vorstellen.

In der beigefügten PDF-Datei finden Sie meinen vollständigen Lebenslauf.

Über die Gelegenheit zu einem kurzen Kennenlernen-Gespräch würde ich mich sehr freuen.

Mit freundlichen Grüßen
"""
    return selected_subject, body, company_final

def run_sender_task(sender_email, sender_pass, data_file_path, cv_path, daily_limit):
    global sender_running
    sender_running = True
    add_log("🔒 الاتصال بسيرفر Gmail SMTP...")

    try:
        file_to_use = data_file_path if (data_file_path and os.path.exists(data_file_path)) else "emails_database.csv"
        if not os.path.exists(file_to_use):
            add_log("❌ لا توجد بيانات للإرسال! قم بتشغيل البحث أو رفع ملف أولاً.")
            sender_running = False
            return

        df = pd.read_excel(file_to_use) if file_to_use.endswith(('.xlsx', '.xls')) else pd.read_csv(file_to_use)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_pass.replace(" ", ""))
        add_log("✅ تم الاتصال بنجاح. بدء الإرسال...")

        sent_count = 0
        for idx, row in df.iterrows():
            if sent_count >= daily_limit: break
            if str(row.get('Status')) == 'Sent': continue

            recipient = str(row['Email']).strip()
            if not recipient or recipient == 'nan': continue

            niche = str(row.get('Niche', '')) if pd.notna(row.get('Niche')) else ""
            city = str(row.get('City', 'Deutschland')) if pd.notna(row.get('City')) else "Deutschland"
            company = str(row.get('Company', '')).strip() if pd.notna(row.get('Company')) else ""
            salutation = str(row.get('Salutation', '')).strip() if pd.notna(row.get('Salutation')) else ""
            person_name = str(row.get('ContactPerson', '')).strip() if pd.notna(row.get('ContactPerson')) else ""

            greeting = f"Sehr geehrte(r) {salutation} {person_name}," if person_name else "Sehr geehrte Damen und Herren,"
            subject, body, resolved_company = generate_hyper_personalized_email(recipient, company, niche, city, greeting)

            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            with open(cv_path, "rb") as f:
                attach = MIMEApplication(f.read(), _subtype="pdf")
                attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(cv_path))
                msg.attach(attach)

            try:
                server.sendmail(sender_email, recipient, msg.as_string())
                df.at[idx, 'Status'] = 'Sent'
                
                if file_to_use.endswith('.xlsx'): df.to_excel(file_to_use, index=False)
                else: df.to_csv(file_to_use, index=False)

                sent_count += 1
                add_log(f"✉️ [{sent_count}/{daily_limit}] تم الإرسال إلى: {recipient} ({resolved_company})")
                
                wait_time = random.randint(60, 120)
                add_log(f"⏳ انتظار أمان: {wait_time} ثانية...")
                time.sleep(wait_time)
            except Exception as e:
                add_log(f"❌ فشل الإرسال إلى {recipient}: {e}")

        server.quit()
        add_log("🏁 اكتملت الحملة بنجاح!")
    except Exception as e:
        add_log(f"❌ خطأ ف الاتصال: {e}")

    sender_running = False

@app.route('/start_send', methods=['POST'])
def start_send():
    global sender_running
    if sender_running: return jsonify({"status": "جاري الإرسال..."})

    email = request.form.get('email')
    password = request.form.get('password')
    daily_limit = int(request.form.get('daily_limit', 40))

    cv_file = request.files['cv_file']
    cv_path = os.path.join(".", cv_file.filename)
    cv_file.save(cv_path)

    data_path = None
    if 'data_file' in request.files and request.files['data_file'].filename != '':
        data_file = request.files['data_file']
        data_path = os.path.join(".", data_file.filename)
        data_file.save(data_path)

    threading.Thread(target=run_sender_task, args=(email, password, data_path, cv_path, daily_limit)).start()
    return jsonify({"status": "تم البدء"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
