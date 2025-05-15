import os
from urllib.parse import urlparse

import pymysql
from flask import (
    Flask, render_template, redirect, url_for, request, session,
    flash, g, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from google.cloud import storage

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME", "gallery")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

# Bucket created/managed by Terraform
GCS_BUCKET = os.getenv("GCS_BUCKET", "se4220-gallery-images")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app = Flask(__name__)
app.secret_key = "some_secret_key"  # change for prod

CATEGORY_TABLE_MAP = {
    1: "cars_trucks", 2: "motorcycles", 3: "boats", 4: "books", 5: "furniture",
    6: "apartments", 7: "houses_rent", 8: "rooms_shared",
    9: "vacation_rentals", 10: "parking_storage",
    11: "automotive_services", 12: "beauty_services",
    13: "computer_services", 14: "household_services",
    15: "tutoring_services", 16: "engineering_jobs",
    17: "healthcare_jobs", 18: "education_jobs",
    19: "customer_service_jobs", 20: "construction_jobs",
    21: "events", 22: "classes", 23: "lost_found",
    24: "volunteers", 25: "general_community",
}

# --------------------------------------------------------------------------- #
# Database helpers                                                            #
# --------------------------------------------------------------------------- #

def _open_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )

def get_db():
    if 'db' not in g:
        g.db = _open_connection()
    return g.db

@app.teardown_appcontext
def teardown_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# --------------------------------------------------------------------------- #
# Utility functions                                                           #
# --------------------------------------------------------------------------- #

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_to_gcs(file_storage, filename):
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(filename)
    blob.upload_from_file(file_storage, content_type=file_storage.content_type)
    return blob.public_url

@app.template_filter('gs_to_public')
def gs_to_public(gs_url):
    if gs_url and gs_url.startswith("gs://"):
        return gs_url.replace("gs://", "https://storage.googleapis.com/")
    return gs_url

# --------------------------------------------------------------------------- #
# Routes: Authentication                                                      #
# --------------------------------------------------------------------------- #

@app.route('/')
def home():
    return redirect(url_for('show_sections' if 'username' in session else 'login'))

@app.route("/index", endpoint="index")
def index_redirect():
    if "username" in session:
        return redirect(url_for("show_sections"))
    return redirect(url_for("login"))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = get_db().cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.update(username=username, user_id=user['id'])
            return redirect(url_for('show_sections'))
        flash("Invalid credentials","error")
    return render_template('login.html')

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = get_db().cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            flash("Username already taken!","error")
            return redirect(url_for('signup'))
        cur.execute(
            "INSERT INTO users (username,password_hash) VALUES (%s,%s)",
            (username, generate_password_hash(password))
        )
        flash("Signup successful! Please log in.","success")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out","info")
    return redirect(url_for('login'))

# --------------------------------------------------------------------------- #
# Routes: Browsing                                                           #
# --------------------------------------------------------------------------- #

@app.route('/sections')
def show_sections():
    cur = get_db().cursor()
    cur.execute("SELECT id,name,description FROM sections")
    sections = cur.fetchall()
    return render_template('sections.html', sections=sections)

@app.route('/categories/<int:section_id>')
def show_categories(section_id):
    cur = get_db().cursor()
    cur.execute(
        "SELECT id,name,description FROM categories WHERE section_id=%s",
        (section_id,)
    )
    categories = cur.fetchall()
    return render_template('categories.html', categories=categories)

@app.route('/items/<int:category_id>')
def show_items(category_id):
    table = CATEGORY_TABLE_MAP.get(category_id) or abort(404)
    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {table}")
    items = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return render_template('items.html', items=items, columns=cols, table_name=table)

@app.route('/item/<string:category_table>/<int:item_id>')
def item_detail(category_table, item_id):
    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {category_table} WHERE id=%s", (item_id,))
    item = cur.fetchone() or abort(404)
    return render_template('item_detail.html', item=item)

# --------------------------------------------------------------------------- #
# Routes: Create Listing                                                      #
# --------------------------------------------------------------------------- #

@app.route('/create', methods=['GET','POST'])
def create_listing():
    # 1) Require login
    if 'username' not in session:
        return redirect(url_for('login'))

    cur = get_db().cursor()

    # 2) Always grab the image object first (it may be None)
    img = request.files.get('image')

    if request.method == 'POST':
        # 3) Validate and lookup the target table
        try:
            cid   = int(request.form['category_id'])
            table = CATEGORY_TABLE_MAP[cid]
        except (KeyError, ValueError):
            flash("Invalid category.","error")
            return redirect(url_for('create_listing'))

        # 4) Pull out all "attr_" form fields
        attrs = {k[5:]: v for k,v in request.form.items() if k.startswith('attr_')}
        if not attrs:
            flash("No attributes provided.","error")
            return redirect(url_for('create_listing'))

        # 5) Ensure each dynamic column exists (MySQL 5.7 safe check)
        for col in attrs:
            cur.execute(
                """SELECT COUNT(*) AS n
                     FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA=%s
                      AND TABLE_NAME=%s
                      AND COLUMN_NAME=%s""",
                (DB_NAME, table, col)
            )
            if cur.fetchone()['n'] == 0:
                col_sql = "`condition`" if col.lower()=="condition" else f"`{col}`"
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_sql} TEXT")

        # 6) Handle optional image upload
        if img and allowed_file(img.filename):
            # 6a) Ensure image_url column exists
            cur.execute(
                """SELECT COUNT(*) AS n
                     FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA=%s
                      AND TABLE_NAME=%s
                      AND COLUMN_NAME='image_url'""",
                (DB_NAME, table)
            )
            if cur.fetchone()['n'] == 0:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN image_url TEXT")

            # 6b) Upload to GCS & append to attrs
            filename = secure_filename(img.filename)
            attrs['image_url'] = upload_to_gcs(img, filename)

        # 7) Build and run the INSERT
        columns     = ", ".join([f"`{c}`" if c.lower()=="condition" else c for c in attrs])
        placeholders= ", ".join(["%s"]*len(attrs))
        cur.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(attrs.values())
        )

        flash("Item listed successfully!","success")
        return redirect(url_for('show_sections'))

    # GET: render the empty form
    cur.execute("SELECT id,name FROM categories")
    return render_template('create_listing.html', categories=cur.fetchall())

@app.route('/visitor')
def visitor():
    return redirect(url_for('show_sections'))

# --------------------------------------------------------------------------- #
# Main                                                                       #
# --------------------------------------------------------------------------- #

if __name__=='__main__':
    app.run(host='0.0.0.0', port=80, debug=False)