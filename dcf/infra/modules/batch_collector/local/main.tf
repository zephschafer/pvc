terraform {
  required_version = ">= 1.0"
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

resource "local_file" "dockerfile" {
  content  = templatefile("${path.module}/templates/batch_collector.Dockerfile.tftpl", {
    java_enabled = var.java_enabled
  })
  filename = "${var.build_context}/Dockerfile"
}

resource "null_resource" "build" {
  depends_on = [local_file.dockerfile]

  triggers = {
    content_hash = var.content_hash
  }

  provisioner "local-exec" {
    command = "docker build -t ${var.image_tag} ${var.build_context}"
  }
}
