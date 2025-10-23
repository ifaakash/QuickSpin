variable "prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "quickspin"
}

##################### NETWORKING #####################

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for Public subnet"
  type        = string
  default     = "10.0.0.0/22"
}

# Deploy a private subnet
variable "private_subnet_cidr" {
  description = "CIDR block for Public subnet"
  type        = string
  default     = "10.0.4.0/22"
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

##################### IAM #####################

variable "role_name" {
  description = "Name of IAM role to be attachecd with the EC2 instance"
  type        = string
  default     = "instance-iam-role"
}

variable "instance_profile_name" {
  description = "Name of IAM Instance profile to be attachecd with the EC2 instance"
  type        = string
  default     = "instance-profiles"
}

##################### INSTANCE #####################

variable "instances" {
  description = "List of Instances to be created"
  type = list(object({
    ami_id        = string
    instance_type = string
    is_public     = bool
  }))
}

variable "user_ip" {
  description = "User's IP address"
  type        = string
}

##################### DEFAULT TAGS #####################
variable "default_tags" {
  description = "Default tags for resources deployment"
  type        = map(string)
  default = {
    "Project"    = "QuickSpin"
    "Created_by" = "ifaakash" # pick github username
  }
}
