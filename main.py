import os
import re
import time
import threading
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from duckduckgo_search import DDGS
import pandas as pd

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bewerbung_app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Multi-User Logs Storage ---
user_scraper_logs = {}
user_sender_logs = {}

def get_user_logs(user_id):
    if user_id not in user_scraper_logs:
        user_scraper_logs[user_id] = []
    if user_id not in user_sender_logs:
        user_sender_logs[user_id] = []
    return user_scraper_logs[user_id], user_sender_logs[user_id]

def log_scraper(user_id, msg):
    s_logs, _ = get_user_logs(user_id)
    s_logs.append(msg)
    if len(s_logs) > 100: s_logs.pop(0)

def log_sender(user_id, msg):
    _, send_logs = get_user_logs(user_id)
    send_logs.append(msg)
    if len(send_logs) > 100: send_logs.pop(0)

# --- Database Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)  # التفعيل من الإدارة
    is_admin = db.Column(db.Boolean, default=False)     # صفتك كأدمن
    emails = db.relationship('ExtractedEmail', backref='owner', lazy=True)

class ExtractedEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(100))
    keyword = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Create Admin Account Automatically ---
with app.app_context():
    db.create_all()
    # إنشاء حساب الأدمن الخاص بك تلقائياً إذا لم يكن موجوداً
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin_user = User(
            username='admin',
            password=generate_password_hash('admin12345', method='scrypt'),
            is_approved=True,
            is_admin=True
        )
        db.session.add(admin_user)
        db.session.commit()

# --- Background Scraper Task ---
def run_scraper_task(user_id, cities, keywords, limit):
    log_scraper(user_id, "🚀 بدأت عملية الاستخراج والتجميع...")
    regex_email = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    found_count = 0

    for city in cities:
        for kw in keywords:
            query = f'"{kw}" "{city}" "E-Mail" OR "Kontakt"'
            log_scraper(user_id, f"📍 فحص مدينة: {city} | الكلمة: {kw}")
            try:
                results = list(DDGS().text(query, max_results=int(limit)))
                for res in results:
                    url = res.get('href', '')
                    try:
                        resp = requests.get(url, timeout=4)
                        if resp.status_code == 200:
                            matches = re.findall(regex_email, resp.text)
                            for em in matches:
                                clean_em = em.lower().strip('.')
                                if not clean_em.endswith(('png', 'jpg', 'jpeg', 'gif', 'svg')):
                                    with app.app_context():
                                        exists = ExtractedEmail.query.filter_by(email=clean_em, user_id=user_id).first()
                                        if not exists:
                                            new_em = ExtractedEmail(email=clean_em, city=city, keyword=kw, user_id=user_id)
                                            db.session.add(new_em)
                                            db.session.commit()
                                            found_count += 1
                    except Exception:
                        continue
            except Exception as e:
                log_scraper(user_id, f"⚠️ تنبيه فـ البحث: {str(e)}")

    log_scraper(user_id, f"🎉 اكتمل البحث! تم حفظ {found_count} إيميل جديد فـ حسابك.")

# --- Background Sender Task ---
def run_sender_task(user_id, gmail_user, gmail_pass, subject, body_text, pdf_data, pdf_name, max_send):
    log_sender(user_id, "🔒 الاتصال بسيرفر Gmail SMTP...")
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=12)
        server.login(gmail_user, gmail_pass)
        log_sender(user_id, "✅ تم الربط مع Gmail بنجاح!")
    except smtplib.SMTPAuthenticationError:
        log_sender(user_id, "❌ خطأ فـ الدخول! تأكد من استخدام App Password الخاص بـ Gmail.")
        return
    except Exception as e:
        log_sender(user_id, f"❌ فشل الاتصال بالسيرفر: {str(e)}")
        return

    with app.app_context():
        user_emails = ExtractedEmail.query.filter_by(user_id=user_id).limit(int(max_send)).all()
        if not user_emails:
            log_sender(user_id, "⚠️ لا توجد إيميلات مستخرجة فـ حسابك للإرسال إليها!")
            server.quit()
            return

        log_sender(user_id, f"📨 بدء إرسال الرسائل إلى {len(user_emails)} مستلم...")
        sent_count = 0

        for item in user_emails:
            try:
                msg = MIMEMultipart()
                msg['From'] = gmail_user
                msg['To'] = item.email
                msg['Subject'] = subject
                msg.attach(MIMEText(body_text, 'plain'))

                if pdf_data:
                    part = MIMEApplication(pdf_data, Name=pdf_name)
                    part['Content-Disposition'] = f'attachment; filename="{pdf_name}"'
                    msg.attach(part)

                server.sendmail(gmail_user, item.email, msg.as_string())
                sent_count += 1
                log_sender(user_id, f"✅ تم الإرسال بنجاح إلى: {item.email}")
                time.sleep(2)
            except Exception as e:
                log_sender(user_id, f"❌ فشل الإرسال إلى {item.email}: {str(e)}")

        server.quit()
        log_sender(user_id, f"🏁 اكتملت الحملة! تم إرسال {sent_count} رسالة بنجاح.")

# --- HTML Layout ---
BASE_LAYOUT = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bewerbung Automation Platform</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: system-ui; }
        .card { background-color: #1e293b; border: 1px solid #334155; }
        .nav-link { color: #94a3b8; font-weight: bold; }
        .nav-link.active { color: #6366f1 !important; border-bottom: 2px solid #6366f1; }
        .log-box { background-color: #090d16; border: 1px solid #1e293b; font-family: monospace; height: 220px; overflow-y: auto; padding: 10px; border-radius: 6px; }
        .form-control { background-color: #0f172a; border: 1px solid #334155; color: #fff; }
        .form-control:focus { background-color: #1e293b; color: #fff; }
    </style>
</head>
<body class="p-3 p-md-4">
    <div class="container" style="max-width: 1000px;">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h3 class="text-primary fw-bold">🚀 Bewerbung Automation</h3>
            {% if current_user.is_authenticated %}
                <div>
                    <span class="me-2 text-light">مرحباً {{ current_user.username }} 👋</span>
                    {% if current_user.is_admin %}
                        <a href="{{ url_for('admin_panel') }}" class="btn btn-warning btn-sm me-2">لوحة الأدمن 👑</a>
                    {% endif %}
                    <a href="{{ url_for('logout') }}" class="btn btn-outline-danger btn-sm">خروج</a>
                </div>
            {% endif %}
        </div>

        {% if current_user.is_authenticated and current_user.is_approved %}
        <ul class="nav nav-tabs mb-4 border-secondary">
            <li class="nav-item">
                <a class="nav-link {% if active_tab == 'scraper' %}active{% endif %}" href="{{ url_for('scraper_page') }}">🔎 1. استخراج الإيميلات</a>
            </li>
            <li class="nav-item">
                <a class="nav-link {% if active_tab == 'sender' %}active{% endif %}" href="{{ url_for('sender_page') }}">📧 2. الإرسال الذكي</a>
            </li>
        </ul>
        {% endif %}

        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

# --- Auth Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('اسم المستخدم مستعمل بالفعل!', 'danger')
            return redirect(url_for('register'))
            
        user = User(
            username=username, 
            password=generate_password_hash(password, method='scrypt'),
            is_approved=False # الحساب كيتسجل معطل حيت خصك تفعلوا أنت
        )
        db.session.add(user)
        db.session.commit()
        flash('تم إنشاء حسابك بنجاح! حسابك فـ طور التفعيل من طرف الإدارة. تواصل معنا لتفعيل الحساب.', 'info')
        return redirect(url_for('login'))
        
    return render_template_string(BASE_LAYOUT + """
    {% block content %}
    <div class="card p-4 mx-auto" style="max-width: 450px;">
        <h4 class="mb-3 text-center">إنشاء حساب جديد</h4>
        <form method="POST">
            <div class="mb-3"><label>اسم المستخدم</label><input type="text" name="username" class="form-control" required></div>
            <div class="mb-3"><label>كلمة السر</label><input type="password" name="password" class="form-control" required></div>
            <button type="submit" class="btn btn-primary w-100">تسجيل الحساب</button>
        </form>
        <p class="mt-3 mb-0 text-center">عندك حساب؟ <a href="{{ url_for('login') }}">سجل الدخول</a></p>
    </div>
    {% endblock %}
    """)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            if not user.is_approved:
                flash('حسابك غير مفعل بعد! المرجو التواصل مع الإدارة للتفعيل.', 'warning')
                return redirect(url_for('unapproved'))
            return redirect(url_for('scraper_page'))
        flash('معلومات الدخول غير صحيحة!', 'danger')
    return render_template_string(BASE_LAYOUT + """
    {% block content %}
    <div class="card p-4 mx-auto" style="max-width: 450px;">
        <h4 class="mb-3 text-center">تسجيل الدخول</h4>
        <form method="POST">
            <div class="mb-3"><label>اسم المستخدم</label><input type="text" name="username" class="form-control" required></div>
            <div class="mb-3"><label>كلمة السر</label><input type="password" name="password" class="form-control" required></div>
            <button type="submit" class="btn btn-primary w-100">دخول</button>
        </form>
        <p class="mt-3 mb-0 text-center">ما عندكش حساب؟ <a href="{{ url_for('register') }}">أنشئ حساباً</a></p>
    </div>
    {% endblock %}
    """)

@app.route('/unapproved')
@login_required
def unapproved():
    if current_user.is_approved:
        return redirect(url_for('scraper_page'))
    return render_template_string(BASE_LAYOUT + """
    {% block content %}
    <div class="card p-4 mx-auto text-center" style="max-width: 500px;">
        <h4 class="text-warning mb-3">⏳ الحساب فـ طور التفعيل</h4>
        <p>شكراً لتسجيلك! حسابك مغلق حالياً حتى يتم تأكيده وتفعيله من طرف Admin.</p>
        <p class="text-muted small">يرجى مراسلتنا لإتمام عملية الاشتراك وتفعيل حسابك فوراً.</p>
        <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm mt-2">تسجيل الخروج</a>
    </div>
    {% endblock %}
    """)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Admin Panel Route ---
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('غير مسموح لك بالدخول لهذه الصفحة!', 'danger')
        return redirect(url_for('scraper_page'))
    users = User.query.filter(User.id != current_user.id).all()
    return render_template_string(BASE_LAYOUT + """
    {% block content %}
    <div class="card p-4">
        <h4 class="mb-3 text-warning">👑 لوحة التحكم بـ الزبائن (Admin Panel)</h4>
        <div class="table-responsive">
            <table class="table table-dark table-striped">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>اسم الزبون</th>
                        <th>حالة الحساب</th>
                        <th>التحكم</th>
                    </tr>
                </thead>
                <tbody>
                    {% for u in users %}
                    <tr>
                        <td>{{ loop.index }}</td>
                        <td>{{ u.username }}</td>
                        <td>
                            {% if u.is_approved %}
                                <span class="badge bg-success">مفعل ✅</span>
                            {% else %}
                                <span class="badge bg-warning text-dark">معطل ⏳</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if u.is_approved %}
                                <a href="/admin/toggle/{{ u.id }}" class="btn btn-sm btn-outline-danger">إلغاء التفعيل ❌</a>
                            {% else %}
                                <a href="/admin/toggle/{{ u.id }}" class="btn btn-sm btn-success">تفعيل الحساب 🚀</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4" class="text-center text-muted">لا يوجد زبائن مسجلون بعد.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endblock %}
    """)

@app.route('/admin/toggle/<int:user_id>')
@login_required
def toggle_user(user_id):
    if not current_user.is_admin:
        return redirect(url_for('scraper_page'))
    user = User.query.get_or_404(user_id)
    user.is_approved = not user.is_approved
    db.session.commit()
    flash(f"تم تغيير حالة حساب الزبون {user.username} بنجاح!", "success")
    return redirect(url_for('admin_panel'))

# --- App Tab 1: Scraper ---
@app.route('/')
@app.route('/scraper', methods=['GET', 'POST'])
@login_required
def scraper_page():
    if not current_user.is_approved: return redirect(url_for('unapproved'))
    
    if request.method == 'POST':
        cities = [c.strip() for c in request.form.get('cities', '').split(',') if c.strip()]
        keywords = [k.strip() for k in request.form.get('keywords', '').split(',') if k.strip()]
        limit = request.form.get('limit', 10)
        
        t = threading.Thread(target=run_scraper_task, args=(current_user.id, cities, keywords, limit))
        t.start()
        flash('بدأت عملية الاستخراج فـ الخلفية!', 'info')
        return redirect(url_for('scraper_page'))

    emails = ExtractedEmail.query.filter_by(user_id=current_user.id).all()
    return render_template_string(BASE_LAYOUT + """
    {% block content %}
    <div class="row">
        <div class="col-md-6 mb-3">
            <div class="card p-3">
                <h5 class="mb-3 text-info">إعدادات البحث والاستخراج</h5>
                <form method="POST">
                    <div class="mb-2"><label>المدن (مفصولة بفارزة)</label><input type="text" name="cities" class="form-control" value="Berlin, Hamburg, München" required></div>
                    <div class="mb-2"><label>الكلمات المفتاحية</label><input type="text" name="keywords" class="form-control" value="Altenpflege, Pflegeheim" required></div>
                    <div class="mb-3"><label>عدد النتائج لكل بحث</label><input type="number" name="limit" class="form-control" value="15" max="50"></div>
                    <button type="submit" class="btn btn-primary w-100">بدء الاستخراج 🔎</button>
                </form>
            </div>
        </div>
        <div class="col-md-6 mb-3">
            <div class="card p-3">
                <h5 class="mb-3 text-warning">📋 سجل الاستخراج المباشر (Scraper Log)</h5>
                <div id="scraperLog" class="log-box text-info">في انتظار بدء الاستخراج...</div>
            </div>
        </div>
    </div>

    <div class="card p-3 mt-2">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h5>الإيميلات المجمعة فـ حسابك ({{ emails|length }})</h5>
            {% if emails %}
                <a href="{{ url_for('export_excel') }}" class="btn btn-success btn-sm">تحميل Excel 📊</a>
            {% endif %}
        </div>
        <div class="table-responsive" style="max-height: 250px;">
            <table class="table table-dark table-striped table-sm">
                <thead><tr><th>#</th><th>الإيميل</th><th>المدينة</th><th>الكلمة</th></tr></thead>
                <tbody>
                    {% for e in emails %}
                    <tr><td>{{ loop.index }}</td><td>{{ e.email }}</td><td>{{ e.city }}</td><td>{{ e.keyword }}</td></tr>
                    {% else %}
                    <tr><td colspan="4" class="text-center text-muted">لا توجد إيميلات مستخرجة بعد.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        setInterval(() => {
            fetch('/api/logs').then(r => r.json()).then(d => {
                document.getElementById('scraperLog').innerText = d.scraper.join('\\n');
            });
        }, 1500);
    </script>
    {% endblock %}
    """, active_tab='scraper')

# --- App Tab 2: Sender ---
@app.route('/sender', methods=['GET', 'POST'])
@login_required
def sender_page():
    if not current_user.is_approved: return redirect(url_for('unapproved'))
    
    if request.method == 'POST':
        gmail_user = request.form.get('gmail_user')
        gmail_pass = request.form.get('gmail_pass')
        subject = request.form.get('subject')
        body_text = request.form.get('body_text')
        max_send = request.form.get('max_send', 45)
        
        pdf_file = request.files.get('pdf_file')
        pdf_data = pdf_file.read() if pdf_file else None
        pdf_name = pdf_file.filename if pdf_file else ""

        t = threading.Thread(target=run_sender_task, args=(current_user.id, gmail_user, gmail_pass, subject, body_text, pdf_data, pdf_name, max_send))
        t.start()
        flash('بدأت حملة الإرسال الذكية فـ الخلفية!', 'info')
        return redirect(url_for('sender_page'))

    return render_template_string(BASE_LAYOUT + """
    {% block content %}
    <div class="row">
        <div class="col-md-7 mb-3">
            <div class="card p-3">
                <h5 class="mb-3 text-success">إعدادات الحملة الذكية (Gmail)</h5>
                <form method="POST" enctype="multipart/form-data">
                    <div class="row">
                        <div class="col-md-6 mb-2"><label>بريد Gmail</label><input type="email" name="gmail_user" class="form-control" placeholder="your@gmail.com" required></div>
                        <div class="col-md-6 mb-2"><label>App Password (16 حرف)</label><input type="password" name="gmail_pass" class="form-control" placeholder="xxxx xxxx xxxx xxxx" required></div>
                    </div>
                    <div class="mb-2"><label>عنوان الرسالة (Subject)</label><input type="text" name="subject" class="form-control" value="Bewerbung um einen Ausbildungsplatz" required></div>
                    <div class="mb-2"><label>نص الرسالة</label><textarea name="body_text" class="form-control" rows="3" required>Sehr geehrte Damen und Herren,...</textarea></div>
                    <div class="row">
                        <div class="col-md-7 mb-2"><label>ملف الـ CV (PDF)</label><input type="file" name="pdf_file" class="form-control" accept=".pdf"></div>
                        <div class="col-md-5 mb-3"><label>الحد الأقصى للإرسال</label><input type="number" name="max_send" class="form-control" value="45"></div>
                    </div>
                    <button type="submit" class="btn btn-success w-100">بدء الحملة الذكية 🚀</button>
                </form>
            </div>
        </div>
        <div class="col-md-5 mb-3">
            <div class="card p-3">
                <h5 class="mb-3 text-success">📨 سجل الإرسال المباشر (Sender Log)</h5>
                <div id="senderLog" class="log-box text-success">في انتظار بدء الحملة...</div>
            </div>
        </div>
    </div>

    <script>
        setInterval(() => {
            fetch('/api/logs').then(r => r.json()).then(d => {
                document.getElementById('senderLog').innerText = d.sender.join('\\n');
            });
        }, 1500);
    </script>
    {% endblock %}
    """, active_tab='sender')

# --- Helper Routes ---
@app.route('/api/logs')
@login_required
def api_logs():
    scraper, sender = get_user_logs(current_user.id)
    return jsonify({"scraper": scraper, "sender": sender})

@app.route('/export')
@login_required
def export_excel():
    if not current_user.is_approved: return redirect(url_for('unapproved'))
    emails = ExtractedEmail.query.filter_by(user_id=current_user.id).all()
    if not emails:
        flash('لا توجد بيانات للتحميل!', 'warning')
        return redirect(url_for('scraper_page'))
    df = pd.DataFrame([{'Email': e.email, 'City': e.city, 'Keyword': e.keyword} for e in emails])
    path = f"/tmp/emails_user_{current_user.id}.xlsx"
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True, download_name="my_extracted_emails.xlsx")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
