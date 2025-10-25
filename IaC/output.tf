output "vpc_id" {
  description = "VPC ID being used by QuickSpin"
  value       = module.ec2_stack.vpc_id
}

output "instance_id" {
  description = "Instance ID being used by QuickSpin"
  value       = module.ec2_stack.instance_id
}

output "security_group_id" {
  value = module.networking.security_group_id
}
