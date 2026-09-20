FROM python:3.12-slim

WORKDIR /app

COPY ./ /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-client \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ansible-core

RUN pip3 install -r requirements.txt
