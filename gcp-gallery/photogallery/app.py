import os
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME", "gallery")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
from google.cloud.sql.connector import Connector
import pymysql
import io
from urllib.parse import urlparse
from google.cloud import storage
from flask import (
    Flask, render_template, redirect, url_for, request, session, flash, g, abort, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

CATEGORY_TABLE_MAP = {
    1: 'cars_trucks',
    2: 'motorcycles',
    3: 'boats',
    4: 'books',
    5: 'furniture',
    6: 'apartments',
    7: 'houses_rent',
    8: 'rooms_shared',
    9: 'vacation_rentals',
    10: 'parking_storage',
    11: 'automotive_services',
    12: 'beauty_services',
    13: 'computer_services',
    14: 'household_services',
    15: 'tutoring_services',
    16: 'engineering_jobs',
    17: 'healthcare_jobs',
    18: 'education_jobs',
    19: 'customer_service_jobs',
    20: 'construction_jobs',
    21: 'events',
    22: 'classes',
    23: 'lost_found',
    24: 'volunteers',
    25: 'general_community'
}


bucketName = 'se4220-project5.appspot.com'

def upload_to_gcs(file, filename):
    client = storage.Client()
    bucket = client.bucket(bucketName)
    blob = bucket.blob(filename)
    blob.upload_from_file(file, content_type=file.content_type)
    blob.make_public()
    return blob.public_url

app = Flask(__name__)
app.secret_key = "some_secret_key"

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

INSTANCE_CONNECTION_NAME = os.getenv("INSTANCE_CONNECTION_NAME")
CLOUD_SQL_PUBLIC_IP = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
connector = Connector()


def get_db():
    connection = connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pymysql",
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )
    return connection

@app.teardown_appcontext
def teardown_db(exception):
    """
    Closes the DB connection at the end of each request if it exists.
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('show_sections'))
    return redirect(url_for('login')) 

@app.template_filter('gs_to_public')
def gs_to_public(gs_url):
    if gs_url and gs_url.startswith("gs://"):
        return gs_url.replace("gs://", "https://storage.googleapis.com/")
    return gs_url

@app.route('/index')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('show_sections'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
       
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db()
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
        user_row = cur.fetchone()
        

        if user_row:
            stored_hash = user_row['password_hash']
            if check_password_hash(stored_hash, password):
                session['username'] = username
                session['user_id'] = user_row['id']
                return redirect(url_for('index'))
        
        flash("Invalid credentials", "error")

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
       
        username = request.form.get('username')
        password = request.form.get('password')

    
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        existing_user = cur.fetchone()
        if existing_user:
            flash("Username already taken!", "error")
            return redirect(url_for('signup'))
        
        hashed_pass = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, hashed_pass)
        )
        conn.commit()

        flash("Signup successful! Please log in.", "success")
        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/sections')
def show_sections():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description FROM sections")
    sections = cur.fetchall()
    return render_template('sections.html', sections=sections)

@app.route('/categories/<int:section_id>')
def show_categories(section_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description FROM categories WHERE section_id=%s", (section_id,))
    categories = cur.fetchall()
    return render_template('categories.html', categories=categories)

@app.route('/items/<int:category_id>')
def show_items(category_id):
    conn = get_db()
    cur = conn.cursor()

    table_name = CATEGORY_TABLE_MAP.get(category_id)

    if not table_name:
        abort(404, "Invalid category selected.")

    cur.execute(f"SELECT * FROM {table_name}")
    items = cur.fetchall()

    
    column_names = [desc[0] for desc in cur.description]

    return render_template('items.html', items=items, columns=column_names, table_name=table_name)


@app.route('/item/<string:category_table>/<int:item_id>')
def item_detail(category_table, item_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(f"SELECT * FROM {category_table} WHERE id=%s", (item_id,))
    item = cur.fetchone()

    if not item:
        abort(404)

    return render_template('item_detail.html', item=item)

@app.route('/create', methods=['GET', 'POST'])
def create_listing():
    if 'username' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        category_id = int(request.form.get('category_id'))
        table_name = CATEGORY_TABLE_MAP.get(category_id)

        if not table_name:
            flash("Invalid category selected.", "error")
            return redirect(url_for('create_listing'))

        form_data = {
        key[5:]: value  # remove 'attr_' prefix
        for key, value in request.form.items()
        if key.startswith('attr_')
        }
        
        if not form_data:
            flash("No attributes provided.", "error")
            return redirect(url_for('create_listing'))
        
        columns = ', '.join([f"`{col}`" if col.lower() == "condition" else col for col in form_data.keys()])
        placeholders = ', '.join(['%s'] * len(form_data))
        values = list(form_data.values())

        image = request.files.get('image')
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image_url = upload_to_gcs(image, filename)
            columns += ', image_url'
            placeholders += ', %s'
            values.append(image_url)

       
        query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
        cur.execute(query, values)
        conn.commit()

        flash("Item listed successfully!", "success")
        return redirect(url_for('index'))

    cur.execute("SELECT id, name FROM categories")
    categories = cur.fetchall()
    return render_template('create_listing.html', categories=categories)


@app.route('/visitor')
def visitor():
    return redirect(url_for('show_sections'))


if __name__ == '__main__':
    app.run(debug=True)
