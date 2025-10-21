'''
Converts quickspin.yml to terraform.tfvars.json format
'''

import yaml
import json
import sys

with open('../quickspin.yml') as f:
    config = yaml.safe_load(f)

# Flatten yaml file
tfvars = {
    "user_ip": config["networking"]["user_ip"] + "/32"
}

instances_data = config.get("instances")

tfvars["instances"] = [
    {
        "ami_id" : instance["ami"],
        "instance_type" : instance["instance_type"],
        "is_public" : instance["is_public"]
    }
    for instance in instances_data if instance
]

# Write to terraform.tfvars.json
with open('terraform.tfvars.json', 'w') as f:
    json.dump(tfvars, f, indent=4)
