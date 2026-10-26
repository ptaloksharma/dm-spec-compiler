# Terraform — isolated infrastructure for agent 'customs-agent'.
terraform {
  required_providers {
    postgresql = { source = "cyrilgdn/postgresql", version = "~> 1.22" }
  }
}

variable "pg_host" { type = string }
variable "pg_user" { type = string }
variable "pg_password" { type = string, sensitive = true }

provider "postgresql" {
  host     = var.pg_host
  username = var.pg_user
  password = var.pg_password
  sslmode  = "require"
}

resource "postgresql_schema" "agent" {
  name = "customs_schema"
}

output "schema_name" { value = postgresql_schema.agent.name }
