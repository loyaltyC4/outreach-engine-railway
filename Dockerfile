FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY engine/ /app/
COPY seed/ /app/seed/
CMD ["python3","-u","run.py"]
