# 1. BASE IMAGE
FROM python:3.10-slim

# 2. WORK DIRECTORY
WORKDIR /app

# 3. DEPENDENCY INSTALLATION
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. COPY SOURCE CODE
COPY . .

# 5. STARTUP COMMAND
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]