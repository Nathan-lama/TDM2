FROM python:3.9-slim

WORKDIR /app

# Installation des dépendances système
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers de dépendances
COPY requirements.txt .

# Installation des dépendances Python avec des logs clairs
RUN pip install --no-cache-dir -r requirements.txt && \
    echo "Dépendances installées:" && \
    pip list

# Copier le code de l'application
COPY . .

# Exposer le port pour l'API
EXPOSE 5001

# Commande par défaut
CMD ["python", "orchestrator.py"]
