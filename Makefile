.DEFAULT_GOAL := help

.PHONY: help setup compile lint plan apply ansible api api-setup db-up db-down expire expire-dry deploy destroy clean

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
	@echo "make api-setup - Create the api/ virtualenv and install FastAPI"
	@echo "make db-up     - Start the local MySQL and the whodb browser UI"
	@echo "make db-down   - Stop them, keeping the data volume"
	@echo "make api       - Serve the dashboard on http://127.0.0.1:8000"
	@echo "make expire    - Revoke every JIT grant past its TTL"
	@echo "make expire-dry- Show what expire would revoke, change nothing"
	@echo "make deploy    - Execute end-to-end flow: compile -> apply -> ansible"
	@echo "make destroy   - Tear down deployed cloud infrastructure"
	@echo "make clean     - Delete temporary generated files"
	@echo "========================================================================"

setup:
	@echo "--> Setting up local environment..."
	python3 -m pip install -r python/requirements.txt
	ansible-galaxy collection install amazon.aws community.aws ansible.posix
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
	cd Ansible && ansible-playbook --syntax-check -i inventories/aws.aws_ec2.yml playbook-install-package.yml

plan: compile
	@echo "--> Planning Infrastructure deployment..."
	cd IaC && terraform init && terraform plan

apply: compile
	@echo "--> Deploying Infrastructure..."
	cd IaC && terraform init && terraform apply -auto-approve

ansible:
	@echo "--> Executing Configuration Management via SSM..."
	cd Ansible && export AWS_REGION=$$(python3 -c 'import yaml; print(yaml.safe_load(open("../quickspin.yml"))["global"]["region"])') && export QUICKSPIN_PREFIX=$$(python3 -c 'import yaml; print(yaml.safe_load(open("../quickspin.yml"))["global"]["project_prefix"])') && export ANSIBLE_CONFIG=ansible.cfg && ansible-playbook -i inventories/aws.aws_ec2.yml playbook-install-package.yml

api-setup:
	@echo "--> Creating the dashboard virtualenv..."
	cd api && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

COMPOSE_DB := docker compose -f docker-db-visualiser-compose.yml

db-up:
	@echo "--> Starting MySQL on :3306 and whodb on http://127.0.0.1:8199 ..."
	$(COMPOSE_DB) up -d

# No -v. The volume is the job and grant history, and dropping it silently is
# not something a stop command should do; remove it deliberately with
# `docker volume rm quickspin_devopshub-mysql-data` when that is what you mean.
db-down:
	@echo "--> Stopping the local database, keeping its volume ..."
	$(COMPOSE_DB) down

# Bound to 127.0.0.1 on purpose. This service runs ansible against real hosts
# and has no authentication, so it must never listen on 0.0.0.0.
#
# MYSQL_PASSWORD matches docker-db-visualiser-compose.yml. The other settings
# already default to the same values in api/app/config.py, so only the password
# has to be supplied here.
api:
	@echo "--> Serving the dashboard on http://127.0.0.1:8000 ..."
	cd api && MYSQL_PASSWORD=devopshub .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Expiry is a command, not a background thread. Point cron, a systemd timer, a
# Kubernetes CronJob or an AWX Schedule at this - expiry then happens whether or
# not the dashboard is running. Safe to run twice: user state=absent is
# idempotent, and an already-revoked grant is not selected again.
expire:
	@echo "--> Revoking expired JIT grants..."
	cd api && MYSQL_PASSWORD=devopshub .venv/bin/python -m app.expire

expire-dry:
	@echo "--> Grants that are past their TTL (no changes made)..."
	cd api && MYSQL_PASSWORD=devopshub .venv/bin/python -m app.expire --dry-run

deploy: compile
	@echo "--> Deploying and Configuring full stack..."
	cd IaC && terraform init && terraform apply -auto-approve
	@echo "--> Waiting 60 seconds for instances and SSM agent registration..."
	sleep 60
	cd Ansible && export AWS_REGION=$$(python3 -c 'import yaml; print(yaml.safe_load(open("../quickspin.yml"))["global"]["region"])') && export QUICKSPIN_PREFIX=$$(python3 -c 'import yaml; print(yaml.safe_load(open("../quickspin.yml"))["global"]["project_prefix"])') && export ANSIBLE_CONFIG=ansible.cfg && ansible-playbook -i inventories/aws.aws_ec2.yml playbook-install-package.yml

destroy:
	@echo "--> Destroying Infrastructure..."
	cd IaC && terraform init && terraform destroy -auto-approve

clean:
	@echo "--> Cleaning up temporary files..."
	rm -f IaC/terraform.tfvars.json
	rm -f python/terraform.tfvars.json
