FROM openjdk:11-slim

# Installer Python 3 et les dépendances nécessaires pour OpenCV
RUN apt-get update || true && \
    # Ajouter un miroir alternatif au cas où le principal ne répond pas
    echo "deb http://archive.debian.org/debian/ stretch main" > /etc/apt/sources.list.d/alternate.list && \
    apt-get update || true && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-numpy \
    # Plutôt que d'installer les packages OpenCV spécifiques qui posent problème,
    # nous installerons simplement ce qui est strictement nécessaire
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# OpenCV sera installé via pip plutôt que les packages système
# Cela évite les problèmes de dépendances système
RUN pip install --no-cache-dir opencv-python-headless scikit-learn numpy

# Copier le code
COPY . .

# Exécuter le tagger d'images
CMD ["python", "tagger.py"]
