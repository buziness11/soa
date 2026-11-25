FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY producer/requirements.txt /tmp/producer-requirements.txt
COPY aggregation/requirements.txt /tmp/aggregation-requirements.txt
RUN pip install --no-cache-dir -r /tmp/producer-requirements.txt -r /tmp/aggregation-requirements.txt
COPY producer/ producer/
COPY aggregation/ aggregation/
COPY schemas/ schemas/
COPY sql/ sql/
COPY tests/ tests/
