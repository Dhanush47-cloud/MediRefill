import os, sqlite3, secrets, hashlib, hmac, csv, io, json
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from flask import Flask, request, redirect, url_for, session, render_template, flash, send_file, abort
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from prescription_ai import extract_prescription, draft_to_dict
from secure_files import encrypt_bytes, decrypt_bytes
import json

APP_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(APP_DIR / "medirefill.db"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(APP_DIR / "private_uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXT = {"png", "jpg", "jpeg", "pdf"}
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-this-before-deploy")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(minutes=30))
csrf = CSRFProtect(app)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def pw_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
    return salt + "$" + digest

def pw_ok(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
        return hmac.compare_digest(check, digest)
    except ValueError:
        return False

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','pharmacist','ops')));
        CREATE TABLE IF NOT EXISTS profiles(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'Self');
        CREATE TABLE IF NOT EXISTS stores(id INTEGER PRIMARY KEY, name TEXT NOT NULL, area TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY, store_id INTEGER REFERENCES stores(id), sku TEXT NOT NULL, product TEXT NOT NULL, schedule TEXT NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL, UNIQUE(store_id,sku));
        CREATE TABLE IF NOT EXISTS prescriptions(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), profile_id INTEGER REFERENCES profiles(id), filename TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending', extracted_text TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, order_code TEXT UNIQUE NOT NULL, user_id INTEGER REFERENCES users(id), profile_id INTEGER REFERENCES profiles(id), store_id INTEGER REFERENCES stores(id), status TEXT NOT NULL, payment_method TEXT NOT NULL, total REAL NOT NULL, created_at TEXT NOT NULL, pharmacist_id INTEGER REFERENCES users(id), verification_note TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), sku TEXT NOT NULL, product TEXT NOT NULL, schedule TEXT NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL, approved INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), profile_id INTEGER REFERENCES profiles(id), sku TEXT NOT NULL, product TEXT NOT NULL, qty_per_day REAL NOT NULL, units_remaining INTEGER NOT NULL, due_date TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS otp_tokens(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        """)
        # Lightweight forward-compatible migration for databases created by earlier MVP versions.
        otp_columns={row[1] for row in c.execute("PRAGMA table_info(otp_tokens)").fetchall()}
        if "attempts" not in otp_columns:
            c.execute("ALTER TABLE otp_tokens ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            c.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)", ("Demo Customer","customer@medirefill.demo",pw_hash("Customer@123"),"customer"))
            c.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)", ("Demo Pharmacist","pharmacist@medirefill.demo",pw_hash("Pharmacist@123"),"pharmacist"))
            c.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)", ("Demo Operations","ops@medirefill.demo",pw_hash("Ops@123"),"ops"))
            uid = c.execute("SELECT id FROM users WHERE role='customer'").fetchone()[0]
            c.execute("INSERT INTO profiles(user_id,name,relation) VALUES(?,?,?)",(uid,"Myself","Self"))
            c.execute("INSERT INTO profiles(user_id,name,relation) VALUES(?,?,?)",(uid,"Mother","Mother"))
            stores = [("Salt Lake","Kolkata",22.5867,88.4170),("Behala","Kolkata",22.4975,88.3176),("Howrah Maidan","Howrah",22.5892,88.3103),("Park Street","Kolkata",22.5535,88.3530)]
            c.executemany("INSERT INTO stores(name,area,lat,lon) VALUES(?,?,?,?)",stores)
            inv = [
            (1,"MET500","Metformin 500 mg · strip of 15","H",50,120),
            (1,"TEL40","Telmisartan 40 mg · strip of 10","H",30,95),
            (1,"LEV50","Levothyroxine 50 mcg · bottle of 100","H",20,190),
            (2,"MET500","Metformin 500 mg · strip of 15","H",40,120),
            (2,"TEL40","Telmisartan 40 mg · strip of 10","H",0,95),
            (3,"MET500","Metformin 500 mg · strip of 15","H",25,120),
            (3,"TEL40","Telmisartan 40 mg · strip of 10","H",15,95),
            (4,"LEV50","Levothyroxine 50 mcg · bottle of 100","H",18,190)]
            c.executemany("INSERT INTO inventory(store_id,sku,product,schedule,qty,price) VALUES(?,?,?,?,?,?)",inv)
            c.execute("INSERT INTO reminders(user_id,profile_id,sku,product,qty_per_day,units_remaining,due_date) VALUES(?,?,?,?,?,?,?)",
                      (uid,1,"MET500","Metformin 500 mg",2,4,(datetime.utcnow()+timedelta(days=2)).date().isoformat()))
            c.commit()

def audit(action, entity, entity_id=None):
    with db() as c:
        c.execute("INSERT INTO audit(actor_id,action,entity,entity_id,created_at) VALUES(?,?,?,?,?)",
                  (session.get("uid"),action,entity,entity_id,datetime.utcnow().isoformat()))

def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            if not session.get("uid"):
                return redirect(url_for("login"))
            if role and session.get("role") not in (role, "ops"):
                abort(403)
            return fn(*a, **kw)
        return wrapped
    return deco

def distance_km(a,b):
    # Haversine
    from math import radians, sin, cos, asin, sqrt
    lat1,lon1,lat2,lon2=map(radians,[a[0],a[1],b[0],b[1]])
    dlat,dlon=lat2-lat1,lon2-lon1
    h=sin(dlat/2)**2+cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return 6371*2*asin(sqrt(h))

def route_store(conn, sku, qty, customer_area="Kolkata"):
    # Demo customer coordinate is central Kolkata; production uses consented delivery pin.
    stores=conn.execute("SELECT s.*,i.qty FROM stores s JOIN inventory i ON i.store_id=s.id WHERE i.sku=? AND i.qty>=?",(sku,qty)).fetchall()
    if not stores: return None
    target=(22.55,88.36)
    return min(stores,key=lambda s: distance_km(target,(s["lat"],s["lon"])))

@app.route("/")
def home():
    if not session.get("uid"): return redirect(url_for("login"))
    if session["role"] in ("pharmacist","ops"): return redirect(url_for("queue"))
    with db() as c:
        profiles=c.execute("SELECT * FROM profiles WHERE user_id=?",(session["uid"],)).fetchall()
        reminders=c.execute("SELECT * FROM reminders WHERE user_id=? AND active=1 ORDER BY due_date",(session["uid"],)).fetchall()
        orders=c.execute("SELECT o.*,s.name store FROM orders o LEFT JOIN stores s ON s.id=o.store_id WHERE o.user_id=? ORDER BY o.id DESC",(session["uid"],)).fetchall()
        products=c.execute("SELECT DISTINCT sku,product,schedule,price FROM inventory ORDER BY product").fetchall()
    return render_template("home.html",profiles=profiles,reminders=reminders,orders=orders,products=products)

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        with db() as c: user=c.execute("SELECT * FROM users WHERE email=?",(request.form.get("email","").strip().lower(),)).fetchone()
        if user and pw_ok(request.form.get("password",""),user["password_hash"]):
            session.clear(); session.permanent=True; session["uid"]=user["id"]; session["role"]=user["role"]; session["name"]=user["name"]
            audit("login","user",user["id"])
            return redirect(url_for("home"))
        flash("Email or password is incorrect.")
    return render_template("login.html")

@app.route("/otp/request", methods=["GET", "POST"])
def otp_request():
    if request.method == "POST":
        email=request.form.get("email", "").strip().lower()
        with db() as c: user=c.execute("SELECT * FROM users WHERE email=? AND role='customer'", (email,)).fetchone()
        if user:
            with db() as c:
                recent=c.execute("SELECT COUNT(*) FROM otp_tokens WHERE user_id=? AND created_at>=?", (user["id"], (datetime.utcnow()-timedelta(hours=1)).isoformat())).fetchone()[0]
            if recent >= 3:
                flash("Too many code requests. Please try again later."); return redirect(url_for("otp_request"))
            code=f"{secrets.randbelow(1000000):06d}"
            digest=hashlib.sha256((code+os.getenv("OTP_PEPPER", "")).encode()).hexdigest()
            expires=(datetime.utcnow()+timedelta(minutes=5)).isoformat()
            with db() as c:
                c.execute("UPDATE otp_tokens SET used=1 WHERE user_id=? AND used=0", (user["id"],))
                c.execute("INSERT INTO otp_tokens(user_id,token_hash,expires_at,created_at) VALUES(?,?,?,?)", (user["id"],digest,expires,datetime.utcnow().isoformat()))
                c.commit()
            try:
                from auth_otp import send_email_otp
                send_email_otp(email, code)
            except Exception as exc:
                app.logger.warning("OTP delivery failed: %s", exc)
                flash("Email OTP could not be sent. Configure SMTP settings and try again.")
                return redirect(url_for("otp_request"))
            session["otp_user_id"]=user["id"]
            flash("A six-digit code has been sent. It expires in five minutes.")
            return redirect(url_for("otp_verify"))
        flash("If the account exists, a code will be sent.")
    return render_template("otp_request.html")

@app.route("/otp/verify", methods=["GET", "POST"])
def otp_verify():
    uid=session.get("otp_user_id")
    if not uid: return redirect(url_for("otp_request"))
    if request.method == "POST":
        code=request.form.get("code", "").strip()
        if not (code.isdigit() and len(code)==6):
            flash("Enter the six-digit code."); return redirect(url_for("otp_verify"))
        digest=hashlib.sha256((code+os.getenv("OTP_PEPPER", "")).encode()).hexdigest()
        with db() as c:
            token=c.execute("SELECT * FROM otp_tokens WHERE user_id=? AND used=0 ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
            valid=bool(token and token["attempts"] < 5 and token["expires_at"]>datetime.utcnow().isoformat() and hmac.compare_digest(token["token_hash"],digest))
            if valid:
                c.execute("UPDATE otp_tokens SET used=1 WHERE id=?", (token["id"],)); user=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone(); c.commit()
            else:
                if token: c.execute("UPDATE otp_tokens SET attempts=attempts+1 WHERE id=?", (token["id"],)); c.commit()
                user=None
        if user:
            session.clear(); session.permanent=True; session["uid"]=user["id"]; session["role"]=user["role"]; session["name"]=user["name"]
            audit("otp_login","user",user["id"]); return redirect(url_for("home"))
        flash("Code is invalid or expired.")
    return render_template("otp_verify.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/order",methods=["POST"])
@login_required("customer")
def create_order():
    sku=request.form.get("sku","").strip()
    try: qty=int(request.form.get("qty","1"))
    except ValueError: qty=0
    try: profile_id=int(request.form.get("profile_id",""))
    except ValueError: profile_id=0
    if qty<1 or qty>100: flash("Enter a quantity between 1 and 100."); return redirect(url_for("home"))
    with db() as c:
        profile=c.execute("SELECT * FROM profiles WHERE id=? AND user_id=?",(profile_id,session["uid"])).fetchone()
        product=c.execute("SELECT * FROM inventory WHERE sku=? LIMIT 1",(sku,)).fetchone()
        if not profile or not product: flash("Select a valid family profile and product."); return redirect(url_for("home"))
        # Prescription is mandatory for all Schedule H items in this demo.
        prescription=request.files.get("prescription")
        if product["schedule"] in ("H","H1") and (not prescription or not prescription.filename):
            flash("A valid prescription upload is required for this Schedule H/H1 item."); return redirect(url_for("home"))
        if product["schedule"] in ("X","Narcotic"):
            flash("This item cannot be ordered online."); return redirect(url_for("home"))
        store=route_store(c,sku,qty)
        if not store: flash("No store has enough stock. Please contact the pharmacy."); return redirect(url_for("home"))
        pid=None
        if prescription and prescription.filename:
            ext=prescription.filename.rsplit(".",1)[-1].lower() if "." in prescription.filename else ""
            if ext not in ALLOWED_EXT: flash("Upload PDF, JPG or PNG only."); return redirect(url_for("home"))
            safe=secure_filename(prescription.filename)
            token=secrets.token_hex(12)
            path=UPLOAD_DIR/(token+"_"+safe+".enc")
            raw_bytes=prescription.read()
            try:
                encrypted=encrypt_bytes(raw_bytes)
                draft=extract_prescription(raw_bytes, safe)
            except Exception as exc:
                flash(str(exc)); return redirect(url_for("home"))
            path.write_bytes(encrypted)
            draft_json=json.dumps(draft_to_dict(draft), ensure_ascii=False)
            cur=c.execute("INSERT INTO prescriptions(user_id,profile_id,filename,status,extracted_text,created_at) VALUES(?,?,?,?,?,?)",
                          (session["uid"],profile_id,path.name,"Pending",draft_json,datetime.utcnow().isoformat()))
            pid=cur.lastrowid
        total=product["price"]*qty
        cur=c.execute("INSERT INTO orders(order_code,user_id,profile_id,store_id,status,payment_method,total,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      ("MR-"+secrets.token_hex(3).upper(),session["uid"],profile_id,store["id"],"Awaiting pharmacist","COD (test)",total,datetime.utcnow().isoformat()))
        oid=cur.lastrowid
        c.execute("INSERT INTO order_items(order_id,sku,product,schedule,qty,price,approved) VALUES(?,?,?,?,?,?,0)",
                  (oid,sku,product["product"],product["schedule"],qty,product["price"]))
        c.commit()
    audit("order_created","order",oid)
    flash(f"Order submitted. Routed to {store['name']}; dispatch is blocked until pharmacist approval.")
    return redirect(url_for("home"))

@app.route("/queue")
@login_required("pharmacist")
def queue():
    with db() as c:
        rows=c.execute("""SELECT o.*,u.name customer,p.name patient,s.name store,oi.product,oi.schedule,oi.qty,pr.id prescription_id,pr.filename,pr.status rx_status,pr.extracted_text
        FROM orders o JOIN users u ON u.id=o.user_id JOIN profiles p ON p.id=o.profile_id JOIN stores s ON s.id=o.store_id
        JOIN order_items oi ON oi.order_id=o.id LEFT JOIN prescriptions pr ON pr.user_id=o.user_id AND pr.profile_id=o.profile_id
        WHERE o.status='Awaiting pharmacist' ORDER BY o.created_at""").fetchall()
    return render_template("queue.html",rows=rows)

@app.route("/verify/<int:order_id>",methods=["POST"])
@login_required("pharmacist")
def verify(order_id):
    decision=request.form.get("decision")
    reason=request.form.get("reason","").strip()
    if decision not in ("approve","reject","reupload"): abort(400)
    if decision!="approve" and len(reason)<5:
        flash("Please enter a clear reason (at least 5 characters)."); return redirect(url_for("queue"))
    with db() as c:
        order=c.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone()
        item=c.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchone()
        if not order or order["status"]!="Awaiting pharmacist": abort(404)
        if decision=="approve":
            c.execute("UPDATE order_items SET approved=1 WHERE order_id=?",(order_id,))
            c.execute("UPDATE orders SET status='Approved – picking',pharmacist_id=?,verification_note=? WHERE id=?",(session["uid"],"Approved by pharmacist",order_id))
        elif decision=="reject":
            c.execute("UPDATE orders SET status='Rejected',pharmacist_id=?,verification_note=? WHERE id=?",(session["uid"],reason,order_id))
        else:
            c.execute("UPDATE orders SET status='Re-upload required',pharmacist_id=?,verification_note=? WHERE id=?",(session["uid"],reason,order_id))
        if item and item["schedule"]=="H1" and decision=="approve":
            c.execute("INSERT INTO audit(actor_id,action,entity,entity_id,created_at) VALUES(?,?,?,?,?)",
                      (session["uid"],"H1_register_entry","order",order_id,datetime.utcnow().isoformat()))
        c.commit()
    audit("prescription_"+decision,"order",order_id)
    flash("Verification decision saved.")
    return redirect(url_for("queue"))

@app.route("/orders")
@login_required()
def orders():
    with db() as c:
        if session["role"]=="customer":
            rows=c.execute("SELECT o.*,s.name store FROM orders o LEFT JOIN stores s ON s.id=o.store_id WHERE o.user_id=? ORDER BY o.id DESC",(session["uid"],)).fetchall()
        else:
            rows=c.execute("SELECT o.*,s.name store FROM orders o LEFT JOIN stores s ON s.id=o.store_id ORDER BY o.id DESC").fetchall()
    return render_template("orders.html",rows=rows)

@app.route("/ops")
@login_required("ops")
def ops():
    with db() as c:
        by_store=c.execute("SELECT s.name,COUNT(o.id) count,COALESCE(SUM(o.total),0) revenue FROM stores s LEFT JOIN orders o ON o.store_id=s.id GROUP BY s.id ORDER BY count DESC").fetchall()
        stats=c.execute("SELECT COUNT(*) total,SUM(CASE WHEN status LIKE 'Approved%' THEN 1 ELSE 0 END) approved,SUM(CASE WHEN status='Rejected' THEN 1 ELSE 0 END) rejected FROM orders").fetchone()
        audit_rows=c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 15").fetchall()
    return render_template("ops.html",by_store=by_store,stats=stats,audit_rows=audit_rows)

@app.route("/reminders")
@login_required("customer")
def reminders():
    with db() as c: rows=c.execute("SELECT * FROM reminders WHERE user_id=? AND active=1 ORDER BY due_date",(session["uid"],)).fetchall()
    return render_template("reminders.html",rows=rows)

@app.route("/reminder/reorder/<int:rid>",methods=["POST"])
@login_required("customer")
def reminder_reorder(rid):
    with db() as c: r=c.execute("SELECT * FROM reminders WHERE id=? AND user_id=? AND active=1",(rid,session["uid"])).fetchone()
    if not r: abort(404)
    # Reorder action returns to the normal checkout where a current prescription is uploaded.
    flash(f"Refill ready: {r['product']}. Submit a current prescription at checkout.")
    return redirect(url_for("home"))

@app.route("/stock/import",methods=["POST"])
@login_required("ops")
def stock_import():
    f=request.files.get("csvfile")
    if not f or not f.filename.lower().endswith(".csv"): flash("Choose a CSV file."); return redirect(url_for("ops"))
    try:
        reader=csv.DictReader(io.StringIO(f.stream.read().decode("utf-8-sig")))
        required={"store_id","sku","product","schedule","qty","price"}
        if not required.issubset(set(reader.fieldnames or [])): raise ValueError("CSV headers must be: "+", ".join(sorted(required)))
        with db() as c:
            for row in reader:
                qty=int(row["qty"]); price=float(row["price"])
                if qty<0 or price<0: raise ValueError("Quantity and price cannot be negative.")
                c.execute("""INSERT INTO inventory(store_id,sku,product,schedule,qty,price) VALUES(?,?,?,?,?,?)
                ON CONFLICT(store_id,sku) DO UPDATE SET product=excluded.product,schedule=excluded.schedule,qty=excluded.qty,price=excluded.price""",
                (int(row["store_id"]),row["sku"].strip(),row["product"].strip(),row["schedule"].strip(),qty,price))
            c.commit()
        audit("stock_csv_import","inventory")
        flash("Stock CSV imported.")
    except Exception as e: flash("Import failed: "+str(e))
    return redirect(url_for("ops"))

@app.route("/prescription/<int:pid>")
@login_required("pharmacist")
def prescription_file(pid):
    with db() as c: p=c.execute("SELECT * FROM prescriptions WHERE id=?",(pid,)).fetchone()
    if not p: abort(404)
    path=UPLOAD_DIR/p["filename"]
    if not path.exists(): abort(404)
    audit("prescription_view","prescription",pid)
    try:
        plaintext=decrypt_bytes(path.read_bytes())
    except Exception:
        abort(500)
    from flask import Response
    suffix=p["filename"].lower()
    mime="application/pdf" if ".pdf.enc" in suffix else ("image/png" if ".png.enc" in suffix else "image/jpeg")
    return Response(plaintext, mimetype=mime, headers={"Content-Disposition":"inline", "Cache-Control":"no-store"})

@app.route("/health")
def health(): return {"status":"ok"}

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1",port=int(os.getenv("PORT","5000")),debug=False)
