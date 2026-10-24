variable "project_id" {
  description = "New globally unique dedicated project ID. Never import a shared project."
  type        = string
}
variable "billing_account" {
  description = "Billing account to link to this disposable project."
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
