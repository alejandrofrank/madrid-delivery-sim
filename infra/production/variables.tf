variable "project_id" {
  type        = string
  description = "New dedicated application project; never an existing shared project."
}
variable "billing_account" {
  type        = string
  description = "Billing account ID; put deployment-specific values in ignored tfvars."
}
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "org_id" {
  type    = string
  default = null
}
variable "replay_image" {
  type        = string
  default     = ""
  description = "Verified replay image pinned by sha256. Empty bootstraps infrastructure only."
  validation {
    condition     = var.replay_image == "" || can(regex("@sha256:[a-f0-9]{64}$", var.replay_image))
    error_message = "Deploy an immutable image digest."
  }
}
variable "monthly_budget" {
  type    = number
  default = 4
  validation {
    condition     = var.monthly_budget > 0 && floor(var.monthly_budget) == var.monthly_budget
    error_message = "Budget must be a positive whole currency amount."
  }
}
variable "active" {
  type        = bool
  default     = false
  description = "Ephemeral environment: false removes Cloud Run and container storage after a demo."
}
variable "budget_currency" {
  type    = string
  default = "EUR"
}
variable "alert_email" {
  type        = string
  default     = ""
  description = "Optional additional notification recipient; billing admins also receive alerts."
}
variable "github_repository" {
  type    = string
  default = "alejandrofrank/madrid-delivery-sim"
}
variable "github_repository_id" {
  type    = string
  default = "1429194351"
}
variable "github_owner_id" {
  type    = string
  default = "46542996"
}
variable "operator_principals" {
  type        = set(string)
  default     = []
  description = "Verified Google identity emails permitted to operate the live API."
}
variable "live_image" {
  type        = string
  default     = ""
  description = "Immutable full-runtime image; live resources are separately opt-in."
}
variable "enable_live" {
  type        = bool
  default     = false
  description = "Provision private live workers and Cloud SQL, which has ongoing costs."
}
variable "enable_vector_search" {
  type        = bool
  default     = false
  description = "Deploy Vertex Vector Search serving nodes; ongoing costs even without requests."
}
variable "live_ready" {
  type        = bool
  default     = false
  description = "Set only after database migrations, scoped service logins and secret versions exist."
}
