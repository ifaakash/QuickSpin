import yaml
import json
import sys

with open('../quickspin.yml') as f:
    config = yaml.safe_load(f)

# Flatten yaml file
tfvars = {
    "user_ip": config["networking"]["user_ip"]
}

# Write to terraform.tfvars.json

with open('terraform.tfvars.json', 'w') as f:
    json.dump(tfvars, f, indent=4)
