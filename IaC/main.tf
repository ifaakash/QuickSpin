module "networking" {
  source = "git::https://github.com/ifaakash/Terraform//Networking?ref=main"
  prefix = var.prefix

  ##################### NETWORKING #####################

  vpc_cidr             = var.vpc_cidr
  public_subnet_cidr   = var.public_subnet_cidr
  private_subnet_cidr  = var.private_subnet_cidr
  enable_dns_hostnames = var.enable_dns_hostnames
  enable_dns_support   = var.enable_dns_support
  user_ip              = var.user_ip
  default_tags         = var.default_tags
}

module "ec2_stack" {
  source   = "git::https://github.com/ifaakash/Terraform//EC2?ref=main"
  for_each = { for index, inst in var.instances : index => inst }
  prefix   = var.prefix

  ##################### INSTANCE #####################

  ami_id               = each.value.ami
  is_public            = each.value.is_public
  instance_type        = each.value.instance_type
  network_interface_id = each.value.is_public ? module.networking.public_network_interface_id : module.networking.private_network_interface_id
  security_group_ids   = [module.networking.security_group_id]
  default_tags         = var.default_tags
  depends_on           = [module.networking]
}
