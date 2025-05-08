import os
import logging
from flask import Flask
from pymongo import MongoClient
from orchestrator_client import OrchestratorClient
from docker_manager import DockerScaler

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialisation de l'application Flask
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Pour les messages flash

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL', 'mongodb://localhost:27017/imagesdb')
client = MongoClient(DB_URL)
db = client.get_database()

# Initialiser le gestionnaire Docker et le client orchestrateur
docker_scaler = DockerScaler()
orchestrator_client = OrchestratorClient()
