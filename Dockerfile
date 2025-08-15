# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements if exists, else create a minimal one
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip
RUN if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

# Copy the rest of the code
COPY . /app

# Install Node dependencies if needed (for frontend/public)
# COPY package.json package-lock.json* ./
# RUN if [ -f package.json ]; then npm install; fi

# Expose the port Chainlit uses
EXPOSE 8000

ENV CHAINLIT_PORT=8000

# Command to run the app
# CMD ["chainlit", "run", "app.py", "-h", "0.0.0.0"]
# CMD ["chainlit", "run", "app.py"]
CMD ["python", "-m", "chainlit", "run", "app.py", "-h", "--host", "0.0.0.0", "--port", "8000"]