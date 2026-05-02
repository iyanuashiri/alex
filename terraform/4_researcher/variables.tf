variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "openai_api_key" {
  description = "OpenAI API key for tracing / OpenAI-compatible clients (optional if openrouter_api_key is set)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "openrouter_api_key" {
  description = "OpenRouter API key; when set and openai_api_key is empty, App Runner gets OPENAI_* aliases"
  type        = string
  default     = ""
  sensitive   = true
}

variable "openai_base_url" {
  description = "Optional OpenAI-compatible base URL; if empty and only OpenRouter is set, defaults to https://openrouter.ai/api/v1"
  type        = string
  default     = ""
  sensitive   = false
}

variable "alex_api_endpoint" {
  description = "Alex API endpoint from Part 3"
  type        = string
}

variable "alex_api_key" {
  description = "Alex API key from Part 3"
  type        = string
  sensitive   = true
}

variable "scheduler_enabled" {
  description = "Enable automated research scheduler"
  type        = bool
  default     = false
}