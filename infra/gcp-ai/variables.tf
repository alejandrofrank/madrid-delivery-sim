variable "project_id" {
  description = "Dedicated simulation project ID. Only import this owned project, never a shared project."
  type        = string
}
variable "billing_account" {
  description = "Billing account linked only while enable_billing=true."
  type        = string
}
variable "org_id" {
  type    = string
  default = null
}
variable "folder_id" {
  type    = string
  default = null
}
variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
}
variable "vertex_region" {
  description = "Vertex location supported by the explicitly selected model."
  type        = string
}
variable "vertex_model" {
  description = "Explicit Google publisher model ID supporting structured generateContent."
  type        = string
}
variable "enable_gateway" {
  type    = bool
  default = false
}
variable "gateway_image" {
  description = "Built gateway image, preferably pinned @sha256 digest."
  type        = string
  default     = ""
}
variable "invoker_members" {
  description = "Explicit human/service principals allowed to mint caller ID tokens."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for member in var.invoker_members : can(regex("^(user|serviceAccount):[^ ]+@[^ ]+$", member))
    ])
    error_message = "Only explicit user or serviceAccount identities may impersonate the caller."
  }
}

variable "enable_runtime" {
  description = "Opt in to billable runtime and image storage. False retains the project, API registrations and free IAM foundation. Disable billing separately after runtime deletion."
  type        = bool
  default     = false
}

variable "enable_billing" {
  description = "Link the selected billing account. Shut down runtime first before setting this false."
  type        = bool
  default     = false
}
