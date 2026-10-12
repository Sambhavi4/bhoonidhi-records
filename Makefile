SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install data footprints raster up down status verify test demo gap baseline redundancy report all clean

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

raster: ## Fetch the DEM the raster processes read (public Copernicus GLO-30)
	./scripts/fetch_dem.sh

demo: ## Run the live walkthrough
	./scripts/demo.sh

up: ## Start the service on :5003 (Processes + Records)
	./scripts/serve_local.sh start

down: ## Stop the service
	./scripts/serve_local.sh stop

status: ## Is it responding?
	./scripts/serve_local.sh status

verify: ## ONE COMMAND: check everything a marker will check
	./scripts/verify.sh

test: ## Run the OGC compliance suite (Processes + Records)
	./scripts/run_tests.sh

gap: ## Audit Bhoonidhi's spatial capability (offline-capable)
	./scripts/probe_gap.sh

baseline: ## Probe ISRO's stack and peer portals for a processing tier (live)
	./scripts/probe_baseline.sh

redundancy: ## Measure what the missing tier costs (needs the service up)
	./scripts/measure_redundancy.py

report: ## Build the LaTeX report -> docs/report/bhoonidhi-processes.pdf
	$(MAKE) -C docs/report

all: install data footprints raster up test ## install -> data -> footprints -> raster -> up -> test

clean:
	rm -f data/bhoonidhi-records.tinydb data/bhoonidhi-records.geojson data/footprints.geojson
	$(MAKE) -C docs/report clean 2>/dev/null || true
