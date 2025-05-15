variable "project_id" {
  description = "The GCP project ID to deploy resources in"
  type        = string
}

variable "region" {
  description = "GCP region for resources (e.g., us-central1)"
  type        = string
  default     = "us-central1"
  validation {
    condition     = contains(["us-central1", "us-east1", "us-west1"], var.region)
    error_message = "Region must be one of the allowed values."
  }
}

variable "vpc_name" {
  description = "Name of the VPC network"
  type        = string
  default     = "se4220-vpc"
}

variable "vpc_cidr" {
  description = "CIDR range for the VPC custom subnet"
  type        = string
  default     = "10.0.0.0/16" # as required
}

variable "subnet_name" {
  description = "Name of the subnet in the VPC"
  type        = string
  default     = "se4220-subnet"
}

variable "subnet_cidr" {
  description = "CIDR for the subnet (subset of vpc_cidr if needed)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "vm_name" {
  description = "Name of the Compute VM instance"
  type        = string
  default     = "se4220-gallery-vm"
}

variable "vm_machine_type" {
  description = "Machine type for the VM"
  type        = string
  default     = "e2-standard-2" # as required
}

variable "vm_zone" {
  description = "GCP zone for the VM (must be in the chosen region)"
  type        = string
  default     = "us-central1-a"
}

variable "db_instance_name" {
  description = "Name of the Cloud SQL instance"
  type        = string
  default     = "se4220-mysql"
}

variable "db_tier" {
  description = "Tier (machine type) for Cloud SQL instance"
  type        = string
  default     = "db-n1-standard-1" # as required (2nd gen)
}

variable "db_user" {
  description = "Database admin username"
  type        = string
  default     = "galleryuser"
}

variable "db_password" {
  description = "Database admin password (sensitive)"
  type        = string
  sensitive   = true
}

variable "bucket_name" {
  description = "GCS bucket for listing images"
  type        = string
  default     = "se4220-project5.appspot.com"
}