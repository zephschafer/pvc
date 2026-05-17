variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
}

variable "pipeline_name" {
  type        = string
  description = "dcf pipeline name (e.g. github_repos)"
}

variable "image_uri" {
  type        = string
  description = "Container image URI for the Cloud Run job"
}

variable "sa_email" {
  type        = string
  description = "Service account email for the Cloud Run job"
}

variable "build_context" {
  type        = string
  description = "Absolute path to the stable build context directory"
}

variable "content_hash" {
  type        = string
  description = "SHA256 of build context files — triggers Cloud Build rebuild when changed"
}

variable "java_enabled" {
  type        = bool
  default     = false
  description = "Install OpenJDK in the container (false for GCP — uses PyArrow direct write)"
}
