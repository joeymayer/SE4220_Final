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

GCS_BUCKET = os.getenv("GCS_BUCKET")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app = Flask(__name__)
app.secret_key = "some_secret_key"          # replace for prod

CATEGORY_TABLE_MAP = {                      # unchanged
    1: "cars_trucks",       2: "motorcycles",            3: "boats",
    4: "books",             5: "furniture",              6: "apartments",
    7: "houses_rent",       8: "rooms_shared",           9: "vacation_rentals",
    10: "parking_storage", 11: "automotive_services",   12: "beauty_services",
    13: "computer_services",14: "household_services",   15: "tutoring_services",
    16: "engineering_jobs",17: "healthcare_jobs",       18: "education_jobs",
    19: "customer_service_jobs", 20: "construction_jobs",
    21: "events",          22: "classes",               23: "lost_found",
    24: "volunteers",      25: "general_community",
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
    if "db" not in g:
        g.db = _open_connection()
    return g.db

@app.teardown_appcontext
def teardown_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()

# --------------------------------------------------------------------------- #
# Utility                                                                     #
# --------------------------------------------------------------------------- #

def allowed_file(fname):
    return "." in fname and fname.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

import uuid

def upload_to_gcs(file_storage, filename):
    # make filename unique: <uuid4>_<original>
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(unique_name)
    blob.upload_from_file(file_storage, content_type=file_storage.content_type)
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{unique_name}"

@app.template_filter("gs_to_public")
def gs_to_public(gs_url):
    if gs_url and gs_url.startswith("gs://"):
        return gs_url.replace("gs://", "https://storage.googleapis.com/")
    return gs_url

# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #

@app.route("/")
def home():
    if "username" in session:
        return redirect(url_for("show_sections"))
    return redirect(url_for("login"))

@app.route("/index")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("show_sections"))

# ---------- Auth ------------------------------------------------------------ #

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cur = get_db().cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username=%s", (username,))
        user = cur.fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.update(username=username, user_id=user["id"])
            return redirect(url_for("index"))

        flash("Invalid credentials", "error")

    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cur = get_db().cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            flash("Username already taken!", "error")
            return redirect(url_for("signup"))

        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, generate_password_hash(password)),
        )
        flash("Signup successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for("login"))

# ---------- Sections / Categories ------------------------------------------ #

@app.route("/sections")
def show_sections():
    cur = get_db().cursor()
    cur.execute("SELECT id, name, description FROM sections")
    return render_template("sections.html", sections=cur.fetchall())

@app.route("/categories/<int:section_id>")
def show_categories(section_id):
    cur = get_db().cursor()
    cur.execute(
        "SELECT id, name, description FROM categories WHERE section_id=%s",
        (section_id,),
    )
    return render_template("categories.html", categories=cur.fetchall())

# ---------- Listings -------------------------------------------------------- #

@app.route("/items/<int:category_id>")
def show_items(category_id):
    table = CATEGORY_TABLE_MAP.get(category_id)
    if not table:
        abort(404, "Invalid category")

    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {table}")
    items = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    return render_template("items.html", items=items, columns=columns, table_name=table)

@app.route("/item/<string:category>/<int:item_id>")
def item_detail(category, item_id):
    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {category} WHERE id=%s", (item_id,))
    item = cur.fetchone() or abort(404)
    return render_template("item_detail.html", item=item)

@app.route("/create", methods=["GET", "POST"])
def create_listing():
    if "username" not in session:
        return redirect(url_for("login"))

    cur = get_db().cursor()

    if request.method == "POST":
        category_id = int(request.form["category_id"])
        table = CATEGORY_TABLE_MAP.get(category_id)
        if not table:
            flash("Invalid category.", "error")
            return redirect(url_for("create_listing"))

        # Extract dynamic attrs
        attrs = {k[5:]: v for k, v in request.form.items() if k.startswith("attr_")}
        if not attrs:
            flash("No attributes provided.", "error")
            return redirect(url_for("create_listing"))

        # Ensure columns exist (TEXT type)
        for col in attrs.keys():
            col_safe = "`condition`" if col.lower() == "condition" else f"`{col}`"

            cur.execute(
                """
                SELECT COUNT(*)
                  FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
                """,
                (DB_NAME, table, col),
            )
            if cur.fetchone()["COUNT(*)"] == 0:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_safe} TEXT")

        # ensure image_url column once
        if img and allowed_file(img.filename):
            cur.execute(
                """
                SELECT COUNT(*)
                  FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = 'image_url'
                """,
                (DB_NAME, table),
            )
            if cur.fetchone()["COUNT(*)"] == 0:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN image_url TEXT")

        columns = ", ".join(
            [f"`{c}`" if c.lower() == "condition" else c for c in attrs.keys()]
        )
        placeholders = ", ".join(["%s"] * len(attrs))
        values = list(attrs.values())

        # Optional image
        img = request.files.get("image")
        if img and allowed_file(img.filename):
            url = upload_to_gcs(img, secure_filename(img.filename))
            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS image_url TEXT"
            )
            columns += ", image_url"
            placeholders += ", %s"
            values.append(url)

        # Insert
        cur.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values)
        flash("Item listed successfully!", "success")
        return redirect(url_for("index"))

    cur.execute("SELECT id, name FROM categories")
    return render_template("create_listing.html", categories=cur.fetchall())

@app.route("/visitor")
def visitor():
    return redirect(url_for("show_sections"))

# --------------------------------------------------------------------------- #
# Run                                                                        #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False)