FROM openjdk:11-slim

# Installer Python 3 et wget
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Installer les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Créer le répertoire pour stocker les images
RUN mkdir -p /data/images

# Exécuter le téléchargeur d'images
CMD ["python", "downloader.py"]
