output "vm_external_ip" {
  description = "Public IP address of the web VM (use this to access the app)"
  value       = google_compute_instance.web_vm.network_interface[0].access_config[0].nat_ip
}

output "web_url" {
  description = "Convenient URL to access the Gallery app"
  value       = "http://${google_compute_instance.web_vm.network_interface[0].access_config[0].nat_ip}"
}

output "db_private_ip" {
  description = "Private IP of the Cloud SQL instance (reachable from VPC)"
  value       = google_sql_database_instance.db_instance.private_ip_address
}

output "db_connection_name" {
  description = "Cloud SQL connection name (for reference or proxy connection)"
  value       = google_sql_database_instance.db_instance.connection_name
}