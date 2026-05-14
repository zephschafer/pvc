output "webserver_url" {
  description = "HTTPS URL of the Cloud Run Airflow service"
  value       = google_cloud_run_v2_service.airflow.uri
}

output "service_name" {
  description = "Name of the Cloud Run Airflow service"
  value       = google_cloud_run_v2_service.airflow.name
}
