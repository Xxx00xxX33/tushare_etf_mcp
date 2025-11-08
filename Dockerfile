# Use an official Python runtime as the base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy dependency file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port for the FastAPI app
EXPOSE 8000

# Command to run the FastAPI server with streaming
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
