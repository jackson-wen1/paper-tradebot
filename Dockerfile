FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the API server (the bot can be started via the API or as a separate process)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
