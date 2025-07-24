# Makefile for managing the GEE Docker container

# --- Variables ---
# Define the name for your docker image. Using ':=' assigns the value once.
IMAGE_NAME := gee-ndvi-exporter

# --- Targets ---

# .PHONY declares targets that are not actual files.
# This ensures 'make' will always run the command regardless of whether
# a file with the same name exists. It's best practice to list all non-file targets.
.PHONY: build run clean

# Build the Docker image.

build:
	@echo "--> Updating requirements.txt..."
	@pip freeze > requirements.txt
	@echo "--> Building Docker image: $(IMAGE_NAME)"
	docker compose build

# Run the Docker container to generate the CSV file.
# I renamed this from 'start_docker' to 'run' for convention.
run:
	@echo "--> Running Docker container..."
	docker compose up

run_sample_export:
	@echo "Running sample export..."
	python app/export_ndvi.py 36.7769 -1.3371 36.8669 -1.2471 2025-06-10 2025-07-01 10000 secrets/ee-creds.json

run_sample_api_call:
	@echo "--> Executing sample POST request to the Docker container..."
	python test_script.py

start_html:
	@echo "--> Starting HTML server..."
	python -m http.server 5001

# A 'clean' target is a helpful convention for removing generated files.
clean:
	@echo "--> Removing generated CSV file..."
	@rm -f output/ndvi_polygons.csv