terraform {
  required_version = ">= 1.3.0"
  backend "gcs" {
    bucket = "se4220-terraform-state"
    prefix = "terraform/state"
  }
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}