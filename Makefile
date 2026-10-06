SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install data up down status test gap all clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create the Python venv
	./scripts/install.sh

data: ## Build the Records catalogue from Bhoonidhi's collection list
	./scripts/build_catalogue.py

up: ## Start the OGC API - Records service
	./scripts/serve_local.sh start

down: ## Stop the service
	./scripts/serve_local.sh stop

status: ## Is it responding?
	./scripts/serve_local.sh status

test: ## Run the OGC API - Records compliance suite
	./scripts/run_tests.sh

gap: ## Re-prove the gap against live Bhoonidhi
	./scripts/probe_gap.sh

all: install data up test ## install -> data -> up -> test

clean:
	rm -f data/bhoonidhi-records.tinydb data/bhoonidhi-records.geojson
