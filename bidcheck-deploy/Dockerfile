FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY send.py .
COPY leads.json .
CMD ["python3","-u","send.py"]
