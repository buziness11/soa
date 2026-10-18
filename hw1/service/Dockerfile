FROM python:3.13-slim
WORKDIR /app
COPY app.py .
# Docker останавливает программу тем же сигналом, что и Ctrl+C.
STOPSIGNAL SIGINT
CMD ["python", "app.py"]
