FROM python:3.8-slim

WORKDIR /app

# Installation des dépendances en une seule étape pour réduire les couches
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Création du répertoire pour les images avant de copier le code
RUN mkdir -p /data/images && \
    chmod 777 /data/images

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code après l'installation des dépendances
COPY . .

# Exposer le port pour l'interface web
EXPOSE 5000

# Exécuter l'application web
CMD ["python", "app.py"]
