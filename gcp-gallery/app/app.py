from flask import Flask
import os
import pymysql  # or mysql.connector depending on which library is in requirements

app = Flask(__name__)

# Database configuration from environment
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME", "gallery")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS")

# Utility: Connect to database to ensure connection works
def get_db_connection():
    return pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME)

@app.route("/")
def index():
    # Try a simple DB query
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES;")
        tables = cursor.fetchall()
        cursor.close()
        conn.close()
        return (f"Gallery application is up! Database tables: {tables}", 200)
    except Exception as e:
        return (f"Gallery application is up, but DB connection failed: {e}", 500)

@app.route("/health")
def health():
    return ("OK", 200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)