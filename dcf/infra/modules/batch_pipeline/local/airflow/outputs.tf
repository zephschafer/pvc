output "webserver_url" {
  description = "URL of the local Airflow webserver"
  value       = "http://localhost:${var.webserver_port}"
}

output "compose_file" {
  description = "Absolute path to the generated docker-compose.yml"
  value       = var.compose_file_path
}
