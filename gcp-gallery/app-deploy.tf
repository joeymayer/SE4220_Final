resource "google_compute_instance" "web_vm" {
  name         = var.vm_name
  machine_type = var.vm_machine_type          # e2-standard-2
  zone         = var.vm_zone
  tags         = ["web-server"]               # matches firewall rule

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-11"
    }
  }

  network_interface {
    network    = google_compute_network.vpc.id
    subnetwork = google_compute_subnetwork.subnet.name

    # Ephemeral public IP for inbound HTTP and outbound package installs
    access_config {}
  }

  service_account {
    email  = google_service_account.vm_service_account.email
    scopes = ["cloud-platform"]               # IAM roles still limit access
  }

  # Pull the script contents from an external file to avoid CRLF issues
  metadata_startup_script = file("${path.module}/startup.sh")

  depends_on = [google_sql_database_instance.db_instance]
}