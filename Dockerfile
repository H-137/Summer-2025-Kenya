# 1. Use a lightweight, official Python 3.12 image based on Debian Bookworm
FROM python:3.12-slim-bookworm

# 2. Set environment variables for best practices
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# 3. Install required system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    g++ \
    libgdal-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 4. Set up the application directory
WORKDIR /app

# 5. Copy and install Python requirements
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# 6. Copy the application code into the container
COPY ./app /app

# 7. Create the output directory inside the container
RUN mkdir -p /app/output

# 8. Define the command to run when the container starts
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001"]
