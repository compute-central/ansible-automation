# Ansible project tasks. `make check` is exactly what CI runs.
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV  := .venv
INV   ?= inventories/dev
PLAY  ?= playbooks/site.yml

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV): requirements.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r requirements.txt
	@touch $(VENV)

.PHONY: install
install: $(VENV) ## Create the venv and install Galaxy collections
	$(VENV)/bin/ansible-galaxy install -r requirements.yml

.PHONY: lint
lint: $(VENV) ## yamllint, then ansible-lint in production profile
	$(VENV)/bin/yamllint .
	$(VENV)/bin/ansible-lint

.PHONY: syntax
syntax: $(VENV) ## Parse every playbook without running anything
	$(VENV)/bin/ansible-playbook --syntax-check -i $(INV) playbooks/*.yml

.PHONY: test
test: $(VENV) ## Unit-test the custom module and filters
	$(VENV)/bin/python -m pytest tests/ -q

.PHONY: check
check: lint syntax test ## Everything CI runs

.PHONY: dry-run
dry-run: $(VENV) ## Converge in check mode with a diff, changing nothing
	$(VENV)/bin/ansible-playbook -i $(INV) $(PLAY) --check --diff

.PHONY: run
run: $(VENV) ## Converge for real (INV=inventories/production PLAY=...)
	$(VENV)/bin/ansible-playbook -i $(INV) $(PLAY)

.PHONY: health
health: $(VENV) ## Probe the fleet with the custom service_health module
	$(VENV)/bin/ansible-playbook -i $(INV) playbooks/health.yml

.PHONY: facts
facts: $(VENV) ## Dump gathered facts for one host (HOST=...)
	$(VENV)/bin/ansible -i $(INV) $(or $(HOST),all) -m ansible.builtin.setup

.PHONY: molecule
molecule: $(VENV) ## Full molecule test of the nginx role (needs Docker)
	$(VENV)/bin/molecule test

.PHONY: converge
converge: $(VENV) ## Molecule converge, leaving the containers up
	$(VENV)/bin/molecule converge

.PHONY: tags
tags: $(VENV) ## List every tag available on the main playbook
	$(VENV)/bin/ansible-playbook -i $(INV) $(PLAY) --list-tags

.PHONY: vault-new
vault-new: $(VENV) ## Create an encrypted vars file (FILE=inventories/dev/group_vars/all/vault.yml)
	$(VENV)/bin/ansible-vault create $(or $(FILE),inventories/dev/group_vars/all/vault.yml)

.PHONY: clean
clean: ## Remove caches, venv, and collections
	rm -rf $(VENV) collections .ansible_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -name '*.retry' -delete
