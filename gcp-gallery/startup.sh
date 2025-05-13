set -euo pipefail

# ---- system setup -----------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive       # skip any install prompts
apt-get update -y
apt-get install -y git python3 python3-pip default-mysql-client
# ---- fetch application code -------------------------------------------------
git clone https://github.com/joeymayer/SE4220_Final.git /opt/se4220 || {
  echo "Git clone failed."
  exit 1
}
cd /opt/se4220/gcp-gallery/app

# ---- python dependencies ----------------------------------------------------
pip3 install --no-cache-dir -r requirements.txt

# ---- database variables -----------------------------------------------------
export DB_HOST="${google_sql_database_instance.db_instance.private_ip_address}"
export DB_NAME="gallery"
export DB_USER="${var.db_user}"
export DB_PASS="${var.db_password}"

# ---- initialise schema (idempotent) -----------------------------------------
mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASS" <<'SQL'
CREATE DATABASE IF NOT EXISTS gallery;
USE gallery;
CREATE TABLE IF NOT EXISTS images (
  id   INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100)
);
SQL

# ---- launch flask app --------------------------------------------------------
export FLASK_APP=app.py
flask run --host=0.0.0.0 --port=80