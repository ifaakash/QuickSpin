terraform {
  backend "s3" {
    bucket       = "quickspin-cfn-lab-state-539772070671-us-east-1"
    key          = "cfnimport.tfstate"
    region       = "us-east-1"
    encrypt      = true
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
