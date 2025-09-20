import yaml
import json
import sys

with open('../quickspin.yml') as f:
    config = yaml.safe_load(f)

# Flatten yaml file
tfvars = {
    "user_ip": config["networking"]["user_ip"] + "/32",
    "is_public": config["networking"]["is_public"],
    "ami_id" : config["instance"]["ami"]
}

# Write to terraform.tfvars.json
with open('terraform.tfvars.json', 'w') as f:
    json.dump(tfvars, f, indent=4)
