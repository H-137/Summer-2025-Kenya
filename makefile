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

run_sample:
	@echo "--> Running Docker container with sample data..."
	@docker run --rm \
		-v "$(shell pwd)/my-secret-key.json:/app/my-secret-key.json:ro" \
		-v "$(shell pwd)/output:/app/output" \
		$(IMAGE_NAME) 36.2597202470 4.19477694745 36.3308408646 4.26022461625 2025-06-05 2025-06-19 10000

# A 'clean' target is a helpful convention for removing generated files.
clean:
	@echo "--> Removing generated CSV file..."
	@rm -f output/ndvi_polygons.csv