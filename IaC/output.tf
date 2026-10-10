output "vpc_id" {
  description = "VPC ID being used by QuickSpin"
  value       = module.networking.vpc_id
}

# output "instance_id" {
#   description = "Instance ID being used by QuickSpin"
#   value       = module.ec2_stack.instance_id
# }

output "security_group_id" {
  value = module.networking.security_group_id
}


output "bastion_instance_id" {
  description = "Instance Id for the bastion server"
  value       = module.bastion[*].instance_id
  # value       = len(module.bastion) > 0 ? module.bastion[0].instance_id : null
}
