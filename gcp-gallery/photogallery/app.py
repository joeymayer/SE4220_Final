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
# Config                                                                      #
# --------------------------------------------------------------------------- #

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME", "gallery")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

# New normal bucket that Terraform creates and grants objectCreator
GCS_BUCKET = "se4220-gallery-images"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app = Flask(__name__)
app.secret_key = "some_secret_key"            # replace in prod

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
# DB helpers                                                                  #
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
def teardown_db(_):
    db = g.pop("db", None)
    if db:
        db.close()

# --------------------------------------------------------------------------- #
# Utility                                                                     #
# --------------------------------------------------------------------------- #

def allowed_file(fname):
    return "." in fname and fname.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_to_gcs(file_storage, filename):
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(filename)
    blob.upload_from_file(file_storage, content_type=file_storage.content_type)
    blob.make_public()
    return blob.public_url

@app.template_filter("gs_to_public")
def gs_to_public(gs_url):
    if gs_url and gs_url.startswith("gs://"):
        return gs_url.replace("gs://", "https://storage.googleapis.com/")
    return gs_url

# --------------------------------------------------------------------------- #
# Routes – Auth                                                               #
# --------------------------------------------------------------------------- #

@app.route("/")
def home():
    return redirect(url_for("show_sections" if "username" in session else "login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form["username"], request.form["password"]
        cur = get_db().cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username=%s", (u,))
        row = cur.fetchone()
        if row and check_password_hash(row["password_hash"], p):
            session.update(username=u, user_id=row["id"])
            return redirect(url_for("show_sections"))
        flash("Invalid credentials", "error")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        u, p = request.form["username"], request.form["password"]
        cur = get_db().cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (u,))
        if cur.fetchone():
            flash("Username already taken!", "error")
            return redirect(url_for("signup"))
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (u, generate_password_hash(p)),
        )
        flash("Signup successful! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for("login"))

# --------------------------------------------------------------------------- #
# Routes – Browse                                                             #
# --------------------------------------------------------------------------- #

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

@app.route("/items/<int:category_id>")
def show_items(category_id):
    table = CATEGORY_TABLE_MAP.get(category_id) or abort(404)
    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {table}")
    items = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return render_template("items.html", items=items, columns=cols, table_name=table)

@app.route("/item/<string:category>/<int:item_id>")
def item_detail(category, item_id):
    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {category} WHERE id=%s", (item_id,))
    item = cur.fetchone() or abort(404)
    return render_template("item_detail.html", item=item)

# --------------------------------------------------------------------------- #
# Routes – Create listing                                                     #
# --------------------------------------------------------------------------- #

@app.route("/create", methods=["GET", "POST"])
def create_listing():
    # Redirect anonymous users to login
    if "username" not in session:
        return redirect(url_for("login"))

    cur = get_db().cursor()

    # Always grab the file object (might be None)
    img = request.files.get("image")

    if request.method == "POST":
        # Get the table for this category
        try:
            category_id = int(request.form["category_id"])
            table = CATEGORY_TABLE_MAP[category_id]
        except (KeyError, ValueError):
            flash("Invalid category.", "error")
            return redirect(url_for("create_listing"))

        # Extract dynamic attributes prefixed by "attr_"
        attrs = {k[5:]: v for k, v in request.form.items() if k.startswith("attr_")}
        if not attrs:
            flash("No attributes provided.", "error")
            return redirect(url_for("create_listing"))

        # Ensure each attribute column exists (MySQL 5.7 safe check)
        for col in attrs:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                  FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA=%s
                   AND TABLE_NAME=%s
                   AND COLUMN_NAME=%s
                """,
                (DB_NAME, table, col),
            )
            if cur.fetchone()["n"] == 0:
                col_safe = "`condition`" if col.lower() == "condition" else f"`{col}`"
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_safe} TEXT")

        # Handle image upload if present and allowed
        if img and allowed_file(img.filename):
            # Ensure image_url column exists
            cur.execute(
                """
                SELECT COUNT(*) AS n
                  FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA=%s
                   AND TABLE_NAME=%s
                   AND COLUMN_NAME='image_url'
                """,
                (DB_NAME, table),
            )
            if cur.fetchone()["n"] == 0:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN image_url TEXT")

            # Upload and append to attrs
            filename = secure_filename(img.filename)
            attrs["image_url"] = upload_to_gcs(img, filename)

        # Build and execute the INSERT
        columns      = ", ".join([f"`{c}`" if c.lower()=="condition" else c for c in attrs])
        placeholders = ", ".join(["%s"] * len(attrs))
        cur.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(attrs.values())
        )

        flash("Item listed successfully!", "success")
        return redirect(url_for("show_sections"))

    # GET: show the create form
    cur.execute("SELECT id, name FROM categories")
    categories = cur.fetchall()
    return render_template("create_listing.html", categories=categories)

@app.route("/visitor")
def visitor():
    return redirect(url_for("show_sections"))

# --------------------------------------------------------------------------- #
# Run                                                                         #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False)