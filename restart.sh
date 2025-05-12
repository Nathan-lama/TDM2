#!/bin/bash
# Arrêter les services
docker-compose down

# Reconstruire le service dashboard
docker-compose build dashboard

# Redémarrer tous les services
docker-compose up -d
