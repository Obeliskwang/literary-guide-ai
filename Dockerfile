FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY libs.txt requirements-api.txt ./

RUN pip install --no-cache-dir -r libs.txt -r requirements-api.txt

COPY . .

EXPOSE 8000 8501
