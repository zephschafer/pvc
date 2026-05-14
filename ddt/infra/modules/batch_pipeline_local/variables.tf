variable "pipeline_name" {
  type        = string
  description = "ddt pipeline name (e.g. github_repos)"
}

variable "build_context" {
  type        = string
  description = "Absolute path to the stable build context directory"
}

variable "image_tag" {
  type        = string
  description = "Docker image tag (e.g. ddt-local/github_repos:latest)"
}

variable "content_hash" {
  type        = string
  description = "SHA256 of build context files — triggers rebuild when changed"
}

variable "java_enabled" {
  type        = bool
  default     = true
  description = "Install OpenJDK in the container (required for local Iceberg/Spark)"
}
