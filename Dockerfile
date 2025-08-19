# # Use an official Python runtime as a parent image
# FROM python:3.11-slim

# # Set environment variables
# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     CHAINLIT_PORT=8000 \
#     CHAINLIT_HOST=0.0.0.0

# # Set work directory
# WORKDIR /app

# # Install system dependencies
# RUN apt-get update && apt-get install -y \
#     build-essential \
#     curl \
#     nodejs \
#     npm \
#     && rm -rf /var/lib/apt/lists/*

# # Copy Python requirements and install
# COPY requirements.txt ./
# RUN pip install --upgrade pip && \
#     pip install --no-cache-dir -r requirements.txt

# # Copy Node.js dependencies and install
# COPY package*.json ./
# RUN npm install

# # Copy Prisma schema and generate client
# COPY prisma ./prisma
# RUN npx prisma generate

# # Copy the rest of the application
# COPY . .

# # Create necessary directories
# RUN mkdir -p /app/.chainlit/data

# # Expose the port Chainlit uses
# EXPOSE 8000

# # Run database migrations and start the app
# CMD ["sh", "-c", "npx prisma migrate deploy && python -m chainlit run app.py --host 0.0.0.0 --port 8000"]


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