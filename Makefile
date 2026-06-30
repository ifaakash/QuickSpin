.DEFAULT_GOAL := help

.PHONY: help setup compile lint plan apply ansible deploy destroy clean

help:
	@echo "========================================================================"
	@echo "                     QUICKSPIN DEV WORKSPACE COMMANDS                   "
	@echo "========================================================================"
	@echo "make setup     - Install Python dependencies, Ansible plugins, and IaC"
	@echo "make compile   - Convert quickspin.yml into IaC/terraform.tfvars.json"
	@echo "make lint      - Validate Python, Terraform, and Ansible syntax"
	@echo "make plan      - Compile configuration and run terraform plan"
	@echo "make apply     - Compile configuration and apply terraform infrastructure"
	@echo "make ansible   - Trigger Ansible playbooks to configure instances over SSM"
	@echo "make deploy    - Execute end-to-end flow: compile -> apply -> ansible"
	@echo "make destroy   - Tear down deployed cloud infrastructure"
	@echo "make clean     - Delete temporary generated files"
	@echo "========================================================================"

setup:
	@echo "--> Setting up local environment..."
	python3 -m pip install -r python/requirements.txt
	ansible-galaxy collection install amazon.aws community.aws
	cd IaC && terraform init

compile:
	@echo "--> Compiling quickspin.yml to JSON..."
	cd python && python3 yaml-to-json.py
	mv python/terraform.tfvars.json IaC/

lint:
	@echo "--> Running Python syntax check..."
	python3 -m flake8 python/yaml-to-json.py --count --select=E9,F63,F7,F82 --show-source --statistics
	@echo "--> Checking Terraform formatting..."
	terraform fmt -check IaC/
	terraform fmt -check ../Terraform/
	@echo "--> Checking Ansible syntax..."
	cd Ansible && ansible-playbook --syntax-check -i inventory_aws.aws_ec2.yml ansible-instruction.yml

plan: compile
	@echo "--> Planning Infrastructure deployment..."
	cd IaC && terraform init && terraform plan

apply: compile
	@echo "--> Deploying Infrastructure..."
	cd IaC && terraform init && terraform apply -auto-approve

ansible:
	@echo "--> Executing Configuration Management via SSM..."
	cd Ansible && export ANSIBLE_CONFIG=ansible.cfg && ansible-playbook -i inventory_aws.aws_ec2.yml ansible-instruction.yml

deploy: compile
	@echo "--> Deploying and Configuring full stack..."
	cd IaC && terraform init && terraform apply -auto-approve
	@echo "--> Waiting 60 seconds for instances and SSM agent registration..."
	sleep 60
	cd Ansible && export ANSIBLE_CONFIG=ansible.cfg && ansible-playbook -i inventory_aws.aws_ec2.yml ansible-instruction.yml

destroy:
	@echo "--> Destroying Infrastructure..."
	cd IaC && terraform init && terraform destroy -auto-approve

clean:
	@echo "--> Cleaning up temporary files..."
	rm -f IaC/terraform.tfvars.json
	rm -f python/terraform.tfvars.json
