module "ec2_stack" {
  source = "git::https://github.com/ifaakash/Terraform//EC2?ref=main"
  prefix = var.prefix

  ##################### NETWORKING #####################

  vpc_cidr             = var.vpc_cidr
  subnet_cidr          = var.subnet_cidr
  enable_dns_hostnames = var.enable_dns_hostnames
  enable_dns_support   = var.enable_dns_support
  user_ip              = var.user_ip
  is_public            = var.is_public

  ##################### INSTANCE #####################

  ami_id        = var.ami_id
  instance_type = var.instance_type
  default_tags  = var.default_tags
}
