FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Copy source
COPY . .

# Expose ports: 8765 (websocket inference), 8000 (dashboard API)
EXPOSE 8765 8000

# Start both inference_engine (websocket) and the FastAPI server
CMD python inference_engine.py & uvicorn api:app --host 0.0.0.0 --port 8000
