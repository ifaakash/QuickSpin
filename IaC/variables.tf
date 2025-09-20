variable "prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "quickspin"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR block for Public subnet"
  type        = string
  default     = "10.0.0.0/22"
}

variable "enable_dns_hostnames" {
  description = "Enable DNS hostnames for the VPC"
  type        = bool
  default     = true
}

variable "enable_dns_support" {
  description = "Enable DNS Support for the VPC"
  type        = bool
  default     = true
}

variable "user_ip" {
  description = "User's IP address"
  type        = string
}

variable "default_tags" {
  description = "Default tags for resources deployment"
  type        = map(string)
  default = {
    "Project"    = "QuickSpin"
    "Created_by" = "ifaakash"
  }
}
