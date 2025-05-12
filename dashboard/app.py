import os
from flask import Flask, send_file
from pymongo import MongoClient
from docker_manager import DockerScaler

# Initialisation de l'application Flask
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL', 'mongodb://localhost:27017/imagesdb')
client = MongoClient(DB_URL)
db = client.get_database()

# Initialiser le gestionnaire Docker
docker_scaler = DockerScaler()

# Ajouter un filtre pour convertir les timestamps en dates lisibles
@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    from datetime import datetime
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

# Importer toutes les routes
from routes.main_routes import *
from routes.image_routes import *
from routes.user_routes import *
from routes.worker_routes import *
from routes.task_routes import *

if __name__ == '__main__':
    # Assurer que les dossiers nécessaires existent
    for folder in ['routes', 'services', 'utils']:
        os.makedirs(folder, exist_ok=True)
        # Créer des fichiers __init__.py vides s'ils n'existent pas
        init_file = os.path.join(folder, '__init__.py')
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                pass
    
    app.run(host='0.0.0.0', port=5000, debug=True)
