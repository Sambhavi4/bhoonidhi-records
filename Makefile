SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install data footprints up down status test demo gap all clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create the Python venv
	./scripts/install.sh

data: ## Build the Records catalogue from Bhoonidhi's collection list
	./scripts/build_catalogue.py

footprints: ## Harvest real acquisition footprints for the spatial processes
	./scripts/fetch_footprints.py --source open --collection sentinel-2-l2a --limit 60
	./scripts/fetch_footprints.py --source open --collection sentinel-1-grd --limit 60 --append

demo: ## Run the live walkthrough
	./scripts/demo.sh

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

all: install data footprints up test ## install -> data -> footprints -> up -> test

clean:
	rm -f data/bhoonidhi-records.tinydb data/bhoonidhi-records.geojson data/footprints.geojson
