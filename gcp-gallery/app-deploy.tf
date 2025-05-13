resource "google_compute_instance" "web_vm" {
  name         = var.vm_name
  machine_type = var.vm_machine_type      # e2-standard-2
  zone         = var.vm_zone
  tags         = ["web-server"]          # apply firewall rules targeting "web-server"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-11"   # OS image for the VM (Debian 11)
    }
  }

  network_interface {
    network    = google_compute_network.vpc.id
    subnetwork = google_compute_subnetwork.subnet.name
    # Allocate an ephemeral public IP to allow internet access:
    access_config {}
  }

  service_account {
    email  = google_service_account.vm_service_account.email
    scopes = ["cloud-platform"]   # broad scope, but IAM roles restrict actual permissions
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    # Update and install necessary packages
    apt-get update -y
    apt-get install -y git python3 python3-pip mysql-client

    # Fetch application code from GitHub (replace URL with Joey's repo if available)
    git clone https://github.com/joeymayer/gallery-app.git /opt/gallery-app || {
      echo "Git clone failed, exiting startup script."
      exit 1
    }

    # Install Python dependencies
    pip3 install -r /opt/gallery-app/requirements.txt

    # Set environment variables for DB connection
    export DB_HOST="${google_sql_database_instance.db_instance.private_ip_address}"
    export DB_NAME="gallery"
    export DB_USER="${var.db_user}"
    export DB_PASS="${var.db_password}"

    # Initialize database schema (if not already initialized)
    mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASS" -e "CREATE DATABASE IF NOT EXISTS gallery; USE gallery; CREATE TABLE IF NOT EXISTS images(id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100));"

    # Start the Flask application (listen on all interfaces, port 80)
    export FLASK_APP=/opt/gallery-app/app.py
    flask run --host=0.0.0.0 --port=80
  EOT

  depends_on = [google_sql_database_instance.db_instance]
}