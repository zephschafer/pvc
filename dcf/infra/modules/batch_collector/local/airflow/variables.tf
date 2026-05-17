variable "image_tag" {
  type        = string
  description = "Docker image tag for the Airflow image (e.g. dcf-airflow-local:latest)"
}

variable "build_context" {
  type        = string
  description = "Absolute path to the Airflow build context directory"
}

variable "content_hash" {
  type        = string
  description = "SHA256 of Airflow Dockerfile template — triggers rebuild when template changes"
}

variable "dag_dir" {
  type        = string
  description = "Absolute host path to the DAGs directory (mounted read-only into scheduler)"
}

variable "warehouse_path" {
  type        = string
  description = "Absolute host path to the warehouse (for DockerOperator volume mounts)"
}

variable "docker_socket" {
  type        = string
  default     = "/var/run/docker.sock"
  description = "Host Docker socket path"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "PostgreSQL password for the local Airflow database"
}

variable "admin_password" {
  type        = string
  sensitive   = true
  description = "Airflow webserver admin password"
}

variable "fernet_key" {
  type        = string
  sensitive   = true
  description = "Airflow fernet key for encrypting connection passwords"
}

variable "compose_file_path" {
  type        = string
  description = "Absolute path where the generated docker-compose.yml will be written"
}

variable "webserver_port" {
  type        = number
  default     = 8090
  description = "Host port to expose the Airflow webserver on"
}
