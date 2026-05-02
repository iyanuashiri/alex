variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "aurora_cluster_arn" {
  description = "ARN of the Aurora cluster from Part 5"
  type        = string
}

variable "aurora_secret_arn" {
  description = "ARN of the Secrets Manager secret from Part 5"
  type        = string
}

variable "vector_bucket" {
  description = "S3 Vectors bucket name from Part 3"
  type        = string
}

variable "bedrock_model_id" {
  description = "Bedrock model ID to use for agents"
  type        = string
}

variable "bedrock_region" {
  description = "AWS region for Bedrock"
  type        = string
}

variable "sagemaker_endpoint" {
  description = "SageMaker endpoint name from Part 2"
  type        = string
  default     = "alex-embedding-endpoint"
}

variable "polygon_api_key" {
  description = "Polygon.io API key for market data"
  type        = string
}

variable "polygon_plan" {
  description = "Polygon.io plan type (free or paid)"
  type        = string
  default     = "free"
}

# LangFuse observability variables (optional)
variable "langfuse_public_key" {
  description = "LangFuse public key for observability (optional)"
  type        = string
  default     = ""
  sensitive   = false
}

variable "langfuse_secret_key" {
  description = "LangFuse secret key for observability (optional)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "langfuse_host" {
  description = "LangFuse host URL (optional)"
  type        = string
  default     = "https://us.cloud.langfuse.com"
}

# OpenAI API key for tracing (optional; can be a real OpenAI key or left empty if using OpenRouter only)
variable "openai_api_key" {
  description = "OpenAI API key for OpenAI-compatible tracing clients (optional if openrouter_api_key is set)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "openrouter_api_key" {
  description = "OpenRouter API key; when set and openai_api_key is empty, Lambdas receive OPENAI_* aliases for tracing"
  type        = string
  default     = ""
  sensitive   = true
}

variable "openai_base_url" {
  description = "Optional OpenAI-compatible API base URL (e.g. https://openrouter.ai/api/v1). If empty and only OpenRouter is set, Terraform sets it automatically."
  type        = string
  default     = ""
  sensitive   = false
}