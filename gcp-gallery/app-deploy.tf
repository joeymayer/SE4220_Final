resource "google_compute_instance" "web_vm" {
  name         = var.vm_name
  machine_type = var.vm_machine_type # e2-standard-2
  zone         = var.vm_zone
  tags         = ["web-server"] # matches firewall rule

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
    scopes = ["cloud-platform"] # IAM roles still limit access
  }

 metadata_startup_script = templatefile(
  "${path.module}/startup.tftpl",
  {
    db_host                  = google_sql_database_instance.db_instance.private_ip_address
    db_user                  = var.db_user
    db_pass                  = var.db_password
    instance_connection_name = google_sql_database_instance.db_instance.connection_name
    bucket_name              = var.bucket_name            
  }
)
  depends_on = [google_sql_database_instance.db_instance]
}