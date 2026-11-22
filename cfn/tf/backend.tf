terraform {
  backend "s3" {
    bucket       = var.state_bucket
    key          = "cdfnimport.tfstate"
    region       = var.region
    encrypt      = true
    use_lockfile = true
  }
}

variable "state_bucket" {
  type    = string
  default = "quickspin-cfn-lab-state-539772070671-us-east-1"
}

variable "region" {
  type    = string
  default = "us-east-1"
}
