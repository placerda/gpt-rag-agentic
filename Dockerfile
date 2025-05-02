# Choose an official base image for Python (e.g., Python 3.12 slim)
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port the application will run on (e.g., 8000)
EXPOSE 80

# Define the entry command: start the Uvicorn server with FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
