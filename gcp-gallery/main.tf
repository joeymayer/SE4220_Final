resource "google_compute_network" "vpc" {
  name                    = var.vpc_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = var.subnet_name
  network       = google_compute_network.vpc.id
  ip_cidr_range = var.subnet_cidr # default 10.0.0.0/16
  region        = var.region
}

resource "google_compute_firewall" "allow_http_https" {
  name    = "${var.vpc_name}-allow-web"
  network = google_compute_network.vpc.name
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]  # allow from anywhere (public internet)
  target_tags   = ["web-server"] # only apply to instances tagged "web-server"
  priority      = 1000
}

resource "google_compute_firewall" "allow_iap_ssh" {
  name      = "${var.vpc_name}-allow-iap-ssh"
  network   = google_compute_network.vpc.name
  direction = "INGRESS"
  priority  = 1000

  source_ranges = ["35.235.240.0/20"] # reserved range for IAP tunnels
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  target_tags = ["web-server"] # same tag your VM already has
}

# (Optional) Firewall rule for SSH (port 22) – restricted to your IP if needed
resource "google_compute_firewall" "allow_ssh" {
  name    = "${var.vpc_name}-allow-ssh"
  network = google_compute_network.vpc.name
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  direction     = "INGRESS"
  source_ranges = ["69.5.155.129"] # replace with your IP range for security Coldwater: 172.58.9.181
  target_tags   = ["web-server"]
  priority      = 1001
}

resource "google_compute_global_address" "private_ip_alloc" {
  name          = "${var.project_id}-sql-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 24 # /24 range for services
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]
}

resource "google_sql_database_instance" "db_instance" {
  name             = var.db_instance_name
  database_version = "MYSQL_8_0" # or MYSQL_5_7, as needed
  region           = var.region
  settings {
    tier = var.db_tier # e.g., db-n1-standard-1
    backup_configuration {
      enabled = true
    }
    ip_configuration {
      ipv4_enabled    = false                         # Disable public IP
      private_network = google_compute_network.vpc.id # use our VPC:contentReference[oaicite:25]{index=25}
      # (Cloud SQL will now only get a private IP within our network)
    }
  }
  root_password = var.db_password # set the root password for MySQL
  depends_on    = [google_service_networking_connection.private_vpc_connection]
}

resource "google_sql_database" "gallery_db" {
  name     = "gallery"
  instance = google_sql_database_instance.db_instance.name
  charset  = "utf8"
}

resource "google_sql_user" "gallery_user" {
  name     = "galleryuser"
  instance = google_sql_database_instance.db_instance.name
  host     = "%"             # allow connection from any host (or specify VM's IP)
  password = var.db_password # reuse the same password for simplicity (or generate a new one)
}

resource "google_service_account" "vm_service_account" {
  account_id   = "gallery-vm-sa"
  display_name = "Gallery VM Service Account"
}

resource "google_project_iam_member" "sa_logs_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.vm_service_account.email}"
}

resource "google_storage_bucket" "images" {
  name                       = var.bucket_name
  location                   = var.region         # same region as everything else
  uniform_bucket_level_access = true
}

# Allow only object creation (no delete)
resource "google_storage_bucket_iam_member" "bucket_writer" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.vm_service_account.email}"
}