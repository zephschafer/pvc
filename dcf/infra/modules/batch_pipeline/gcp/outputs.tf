output "job_name" {
  description = "Name of the provisioned Cloud Run job"
  value       = google_cloud_run_v2_job.pipeline.name
}
