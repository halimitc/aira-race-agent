FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Force UTF-8 encoding in Python logs
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=UTF-8

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . .

# Run the agent in automated mode 1 (Live Race)
CMD ["python", "app.py", "--mode", "1"]
