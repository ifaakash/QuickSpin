"""
Converts quickspin.yml to terraform.tfvars.json format with robust validation.
"""

import ipaddress
import json
import os
import sys
import yaml

CONFIG_PATH = "../quickspin.yml"
OUTPUT_PATH = "terraform.tfvars.json"


def error_exit(message: str):
    """Prints a structured error message to stderr and exits with code 1."""
    sys.stderr.write(f"\n[PARSER ERROR] {message}\n\n")
    sys.exit(1)


def main():
    # 1. Check if configuration file exists
    if not os.path.exists(CONFIG_PATH):
        error_exit(
            f"Configuration file not found at '{CONFIG_PATH}'. Please create this file."
        )

    # 2. Parse YAML file with safe loading and syntax checks
    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        error_exit(f"Failed to parse YAML file. Syntax error:\n{exc}")
    except Exception as exc:
        error_exit(f"An unexpected error occurred while reading the config: {exc}")

    if not config:
        error_exit("Configuration file is empty.")

    # 2.5 Validate 'global' section
    if "global" not in config or not isinstance(config["global"], dict):
        error_exit("Missing or invalid 'global' block in configuration.")
    
    global_config = config["global"]
    if "region" not in global_config or "project_prefix" not in global_config:
        error_exit("Missing 'region' or 'project_prefix' under 'global' block.")
    
    region = str(global_config["region"]).strip()
    prefix = str(global_config["project_prefix"]).strip()

    # Formulate tfvars output dictionary
    tfvars = {
        "region": region,
        "prefix": prefix,
    }

    # 3. Validate 'networking' section
    if "networking" not in config or not isinstance(config["networking"], dict):
        error_exit("Missing or invalid 'networking' block in configuration.")

    networking = config["networking"]

    if "user_ip" not in networking:
        error_exit("Missing 'user_ip' parameter under 'networking' block.")

    raw_ip = str(networking["user_ip"]).strip()

    # Validate IP address syntax
    try:
        ipaddress.ip_address(raw_ip)
    except ValueError:
        error_exit(
            f"Invalid IP address format: '{raw_ip}'. Must be a valid IPv4 or IPv6 address (e.g. 192.168.1.1)."
        )

    # Formulate tfvars output dictionary
    tfvars["user_ip"] = f"{raw_ip}/32"

    # 4. Validate 'instances' section
    if "instances" not in config:
        error_exit("Missing 'instances' block in configuration.")

    instances_data = config["instances"]
    if not isinstance(instances_data, list):
        error_exit("'instances' must be a list of instance definitions.")

    if not instances_data:
        error_exit("'instances' list cannot be empty.")

    validated_instances = []

    for i, instance in enumerate(instances_data):
        if not instance:
            continue

        if not isinstance(instance, dict):
            error_exit(
                f"Instance definition at index {i} is invalid. It must be a YAML object."
            )

        # Check required instance fields
        required_fields = ["ami", "instance_type", "is_public"]
        for field in required_fields:
            if field not in instance:
                error_exit(
                    f"Instance at index {i} is missing the required parameter: '{field}'."
                )

        ami = str(instance["ami"]).strip()
        instance_type = str(instance["instance_type"]).strip()
        is_public = instance["is_public"]

        if not ami.startswith("ami-"):
            error_exit(
                f"Invalid AMI ID format: '{ami}' at index {i}. AWS AMIs must start with 'ami-'."
            )

        # Ensure is_public is a strict boolean
        if not isinstance(is_public, bool):
            error_exit(
                f"Invalid value for 'is_public' at index {i}: '{is_public}'. Must be an absolute boolean (true or false)."
            )

        # Validate packages list if specified
        packages_list = instance.get("packages", [])
        if not isinstance(packages_list, list):
            error_exit(
                f"'packages' at index {i} must be defined as a YAML list of strings."
            )

        # Join the list elements into a comma-separated string for Terraform
        joined_packages = ",".join(str(pkg).strip() for pkg in packages_list)

        validated_instances.append(
            {
                "ami_id": ami,
                "instance_type": instance_type,
                "is_public": is_public,
                "packages": joined_packages,
            }
        )

    tfvars["instances"] = validated_instances

    # 5. Write to output tfvars JSON
    try:
        with open(OUTPUT_PATH, "w") as f:
            json.dump(tfvars, f, indent=4)
        print(f"Successfully converted '{CONFIG_PATH}' to '{OUTPUT_PATH}'.")
    except Exception as exc:
        error_exit(f"Failed to write TFVARS JSON output: {exc}")


if __name__ == "__main__":
    main()
