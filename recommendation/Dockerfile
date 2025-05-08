FROM openjdk:11-slim

# Installer Python 3
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Installer les dépendances
COPY requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Exécuter le système de recommandation
CMD ["python", "recommender.py"]
