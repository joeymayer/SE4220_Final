import os
import io
from urllib.parse import urlparse

import pymysql
from flask import (
    Flask, render_template, redirect, url_for, request, session,
    flash, g, abort, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from google.cloud import storage

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# DB creds come from startup script env vars
DB_HOST = os.getenv("DB_HOST")                  # 10.x.x.x private IP
DB_NAME = os.getenv("DB_NAME", "gallery")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

# GCS bucket for image uploads
GCS_BUCKET = "se4220-project5.appspot.com"

# Allowed upload extensions
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# Flask setup
app = Flask(__name__)
app.secret_key = "some_secret_key"              # replace in prod

# Category->table mapping (unchanged)
CATEGORY_TABLE_MAP = {
    1: "cars_trucks",
    2: "motorcycles",
    3: "boats",
    4: "books",
    5: "furniture",
    6: "apartments",
    7: "houses_rent",
    8: "rooms_shared",
    9: "vacation_rentals",
    10: "parking_storage",
    11: "automotive_services",
    12: "beauty_services",
    13: "computer_services",
    14: "household_services",
    15: "tutoring_services",
    16: "engineering_jobs",
    17: "healthcare_jobs",
    18: "education_jobs",
    19: "customer_service_jobs",
    20: "construction_jobs",
    21: "events",
    22: "classes",
    23: "lost_found",
    24: "volunteers",
    25: "general_community",
}

# --------------------------------------------------------------------------- #
# Database helpers                                                            #
# --------------------------------------------------------------------------- #

def _open_connection():
    """Return a new PyMySQL connection."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

def get_db():
    """
    Lazily attach a DB connection to `g` for the current request.
    Flask automatically resets `g` each request cycle.
    """
    if "db" not in g:
        g.db = _open_connection()
    return g.db

@app.teardown_appcontext
def teardown_db(exception):
    """Close the connection at the end of the request, if it exists."""
    db = g.pop("db", None)
    if db is not None:
        db.close()

# --------------------------------------------------------------------------- #
# Utility functions                                                           #
# --------------------------------------------------------------------------- #

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_to_gcs(file_storage, filename):
    """Upload a Flask `FileStorage` to Google Cloud Storage and return public URL."""
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(filename)
    blob.upload_from_file(file_storage, content_type=file_storage.content_type)
    blob.make_public()
    return blob.public_url

# --------------------------------------------------------------------------- #
# Jinja filters                                                               #
# --------------------------------------------------------------------------- #

@app.template_filter("gs_to_public")
def gs_to_public(gs_url):
    """Convert a gs:// URL to a public https://storage.googleapis.com/ URL."""
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

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        cur = get_db().cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
        user_row = cur.fetchone()

        if user_row and check_password_hash(user_row["password_hash"], password):
            session["username"] = username
            session["user_id"] = user_row["id"]
            return redirect(url_for("index"))

        flash("Invalid credentials", "error")

    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        cur = get_db().cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            flash("Username already taken!", "error")
            return redirect(url_for("signup"))

        hashed_pass = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, hashed_pass),
        )
        flash("Signup successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route("/sections")
def show_sections():
    cur = get_db().cursor()
    cur.execute("SELECT id, name, description FROM sections")
    sections = cur.fetchall()
    return render_template("sections.html", sections=sections)

@app.route("/categories/<int:section_id>")
def show_categories(section_id):
    cur = get_db().cursor()
    cur.execute(
        "SELECT id, name, description FROM categories WHERE section_id=%s", (section_id,)
    )
    categories = cur.fetchall()
    return render_template("categories.html", categories=categories)

@app.route("/items/<int:category_id>")
def show_items(category_id):
    table_name = CATEGORY_TABLE_MAP.get(category_id)
    if not table_name:
        abort(404, "Invalid category selected.")

    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {table_name}")
    items = cur.fetchall()
    column_names = [desc[0] for desc in cur.description]

    return render_template(
        "items.html", items=items, columns=column_names, table_name=table_name
    )

@app.route("/item/<string:category_table>/<int:item_id>")
def item_detail(category_table, item_id):
    cur = get_db().cursor()
    cur.execute(f"SELECT * FROM {category_table} WHERE id=%s", (item_id,))
    item = cur.fetchone()
    if not item:
        abort(404)
    return render_template("item_detail.html", item=item)

@app.route("/create", methods=["GET", "POST"])
def create_listing():
    if "username" not in session:
        return redirect(url_for("login"))

    cur = get_db().cursor()

    if request.method == "POST":
        category_id = int(request.form.get("category_id"))
        table_name = CATEGORY_TABLE_MAP.get(category_id)

        if not table_name:
            flash("Invalid category selected.", "error")
            return redirect(url_for("create_listing"))

        # Extract dynamic form attributes (prefixed with attr_)
        form_data = {
            key[5:]: value for key, value in request.form.items() if key.startswith("attr_")
        }
        if not form_data:
            flash("No attributes provided.", "error")
            return redirect(url_for("create_listing"))

        columns = ", ".join(
            [f"`{col}`" if col.lower() == "condition" else col for col in form_data.keys()]
        )
        placeholders = ", ".join(["%s"] * len(form_data))
        values = list(form_data.values())

        # Handle optional image upload
        image = request.files.get("image")
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image_url = upload_to_gcs(image, filename)
            columns += ", image_url"
            placeholders += ", %s"
            values.append(image_url)

        query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
        cur.execute(query, values)
        flash("Item listed successfully!", "success")
        return redirect(url_for("index"))

    cur.execute("SELECT id, name FROM categories")
    categories = cur.fetchall()
    return render_template("create_listing.html", categories=categories)

@app.route("/visitor")
def visitor():
    return redirect(url_for("show_sections"))

# --------------------------------------------------------------------------- #
# Main entry                                                                   #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # Debug off in production; Flask will still bind to 0.0.0.0:80 from startup script
    app.run(host="0.0.0.0", port=80, debug=False)