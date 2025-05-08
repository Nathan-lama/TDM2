from pymongo import MongoClient
import time
import json
import os
import logging
import requests
from pyspark.sql import SparkSession
import threading
import autoscaler
import api

# Configuration du logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('orchestrator')

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL')
client = MongoClient(DB_URL)
db = client.get_database()

# Configuration Spark
spark = SparkSession.builder \
    .appName("ImageRecommendationOrchestrator") \
    .config("spark.jars.packages", "org.mongodb.spark:mongo-spark-connector_2.12:3.0.1") \
    .getOrCreate()

# Constantes pour l'autoscaling
IMAGES_PER_WORKER = autoscaler.IMAGES_PER_WORKER
MAX_WORKERS = autoscaler.MAX_WORKERS
DOCKER_NETWORK = "partie2_app_network"
DOCKER_PROJECT = "partie2"

def init_database():
    """Initialise les collections MongoDB si elles n'existent pas"""
    collections = db.list_collection_names()
    
    # Créer les collections nécessaires
    if "images" not in collections:
        db.create_collection("images")
        logger.info("Collection 'images' créée")
    
    if "tags" not in collections:
        db.create_collection("tags")
        logger.info("Collection 'tags' créée")
    
    if "users" not in collections:
        db.create_collection("users")
        logger.info("Collection 'users' créée")
    
    if "recommendations" not in collections:
        db.create_collection("recommendations")
        logger.info("Collection 'recommendations' créée")

def load_image_sources():
    """Charge les sources d'images à télécharger"""
    # Dans un cas réel, cela pourrait provenir d'une API ou d'un fichier
    # Ici, on simule une liste d'URLs d'images
    return [
        f"https://picsum.photos/id/{i}/800/600" for i in range(1, 101)
    ]

def ensure_worker_container(worker_type, worker_id):
    """Vérifie si un conteneur existe pour ce worker et le crée si nécessaire"""
    try:
        import docker
        docker_client = docker.from_env()
        
        # Vérifier si un conteneur existe déjà pour ce worker
        service_name = f"image_{worker_type}"
        container_name = f"{service_name}_{worker_id}"
        
        try:
            # Rechercher par nom exact
            container = docker_client.containers.get(container_name)
            if container.status != "running":
                logger.info(f"Redémarrage du conteneur {container_name} (statut: {container.status})")
                container.restart()
            return True
        except docker.errors.NotFound:
            # Le conteneur n'existe pas, on doit le créer
            pass
        
        # Rechercher un conteneur modèle pour ce service
        template = None
        containers = docker_client.containers.list(all=True, 
                            filters={"label": [f"com.docker.compose.service={service_name}"]})
        
        for c in containers:
            if c.status == "running":
                template = c
                break
        
        if template:
            # Utiliser le conteneur modèle comme base
            image_name = template.image.tags[0] if template.image.tags else f"{DOCKER_PROJECT}_{service_name}"
            logger.info(f"Création du conteneur {container_name} basé sur {image_name}")
        else:
            # Pas de modèle - utiliser l'image par défaut
            image_name = f"{DOCKER_PROJECT}_{service_name}"
            logger.info(f"Création du conteneur {container_name} avec l'image par défaut {image_name}")
        
        # Variables d'environnement
        env_vars = {
            "WORKER_ID": str(worker_id),
            "DATABASE_URL": "mongodb://database:27017/imagesdb"
        }
        
        # Créer le conteneur
        new_container = docker_client.containers.run(
            image_name,
            detach=True,
            name=container_name,
            network=DOCKER_NETWORK,
            environment=env_vars,
            volumes={
                f"{DOCKER_PROJECT}_shared_data": {"bind": "/data", "mode": "rw"}
            },
            labels={
                "com.docker.compose.project": DOCKER_PROJECT,
                "com.docker.compose.service": service_name,
                "worker_id": str(worker_id)
            }
        )
        
        logger.info(f"✅ Conteneur {container_name} créé avec succès (ID: {new_container.id[:12]})")
        return True
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création/vérification du conteneur {worker_type}_{worker_id}: {e}")
        import traceback
        traceback.print_exc()
        return False

def distribute_download_tasks():
    """Distribue les tâches de téléchargement aux instances image_downloader"""
    image_sources = load_image_sources()
    
    # Calculer le nombre de workers nécessaires
    worker_count = max(1, min(MAX_WORKERS, (len(image_sources) + IMAGES_PER_WORKER - 1) // IMAGES_PER_WORKER))
    
    # S'assurer que les conteneurs existent pour chaque worker
    for worker_id in range(1, worker_count + 1):
        ensure_worker_container("downloader", worker_id)
    
    # Distribuer les URLs entre les workers
    tasks_by_worker = {}
    for i, url in enumerate(image_sources):
        worker_id = (i % worker_count) + 1
        if worker_id not in tasks_by_worker:
            tasks_by_worker[worker_id] = []
        tasks_by_worker[worker_id].append(url)
    
    # Sauvegarder les tâches dans la base de données
    for worker_id, urls in tasks_by_worker.items():
        task_id = f"download_{time.time()}_{worker_id}"
        db.download_tasks.insert_one({
            "_id": task_id,
            "worker_id": worker_id,
            "urls": urls,
            "status": "pending",
            "created_at": time.time()
        })
    
    logger.info(f"Tâches de téléchargement distribuées: {len(image_sources)} URLs réparties entre {len(tasks_by_worker)} workers")
    return len(tasks_by_worker)

def distribute_tagging_tasks():
    """Distribue les tâches de tagging aux instances image_tagger"""
    # Récupérer les images téléchargées qui n'ont pas encore été taguées
    downloaded_images = list(db.images.find({"tagged": {"$ne": True}}, {"_id": 1}))
    
    if not downloaded_images:
        logger.info("Aucune image à tagger.")
        return False
    
    # Extraire uniquement les IDs des images
    image_ids = [img["_id"] for img in downloaded_images]
    logger.info(f"Trouvé {len(image_ids)} images à tagger")
    
    # Calculer le nombre de workers nécessaires basé sur 20 images par worker
    worker_count = (len(image_ids) + IMAGES_PER_WORKER - 1) // IMAGES_PER_WORKER
    worker_count = max(1, min(worker_count, MAX_WORKERS))
    
    # S'assurer que les conteneurs existent pour chaque worker
    for worker_id in range(1, worker_count + 1):
        ensure_worker_container("tagger", worker_id)
    
    # Diviser les IDs entre les workers
    tasks_by_worker = {}
    for i, image_id in enumerate(image_ids):
        worker_id = (i % worker_count) + 1
        if worker_id not in tasks_by_worker:
            tasks_by_worker[worker_id] = []
        tasks_by_worker[worker_id].append(image_id)
    
    # Créer une tâche pour chaque worker
    for worker_id, worker_image_ids in tasks_by_worker.items():
        task_id = f"tag_{time.time()}_{worker_id}"
        db.tagging_tasks.insert_one({
            "_id": task_id,
            "worker_id": worker_id,
            "image_ids": worker_image_ids,
            "status": "pending",
            "created_at": time.time()
        })
    
    logger.info(f"Tâches de tagging créées: {len(image_ids)} images réparties entre {len(tasks_by_worker)} workers")
    
    # Déclencher l'autoscaling
    threading.Thread(target=update_worker_scaling).start()
    
    return True

def trigger_recommendations():
    """Déclenche la génération de recommandations"""
    # Vérifier si suffisamment d'images ont été taguées
    tagged_count = db.images.count_documents({"tagged": True})
    
    if tagged_count >= 50:  # Seuil arbitraire pour déclencher les recommandations
        # Récupérer tous les utilisateurs
        users = list(db.users.find({}))
        
        # Créer une tâche de recommandation
        db.recommendation_tasks.insert_one({
            "user_ids": [user["_id"] for user in users],
            "status": "pending",
            "created_at": time.time()
        })
        
        logger.info(f"Tâche de recommandation créée pour {len(users)} utilisateurs")
    else:
        logger.info(f"Pas assez d'images taguées ({tagged_count}/50) pour déclencher les recommandations")

def monitor_progress():
    """Surveille l'avancement des tâches et coordonne le flux de travail"""
    # Vérifier l'avancement des téléchargements
    download_complete = all(
        task["status"] == "completed" 
        for task in db.download_tasks.find({})
    )
    
    # Vérifier l'avancement du tagging
    tagging_tasks = list(db.tagging_tasks.find({}))
    tagging_complete = all(
        task["status"] == "completed" for task in tagging_tasks
    ) if tagging_tasks else False
    
    # Vérifier l'avancement des recommandations
    recommendation_tasks = list(db.recommendation_tasks.find({}))
    recommendations_complete = all(
        task["status"] == "completed" for task in recommendation_tasks
    ) if recommendation_tasks else False
    
    logger.info(f"État du système - Téléchargements: {'OK' if download_complete else 'En cours'}, "
                f"Tagging: {'OK' if tagging_complete else 'En cours'}, "
                f"Recommandations: {'OK' if recommendations_complete else 'En attente/En cours'}")
    
    return {
        "download_complete": download_complete,
        "tagging_complete": tagging_complete,
        "recommendations_complete": recommendations_complete
    }

def main():
    """Fonction principale de l'orchestrateur"""
    logger.info("Démarrage de l'orchestrateur")
    
    # Initialiser la base de données
    init_database()
    
    # Démarrer l'autoscaler dans un thread séparé
    autoscaler_thread = autoscaler.start_autoscaler()
    logger.info("Autoscaler démarré dans un thread séparé")
    
    # Démarrer le serveur API dans un thread séparé
    api_thread = threading.Thread(target=api.start_api_server, kwargs={'debug': False}, daemon=True)
    api_thread.start()
    logger.info("API REST démarrée sur le port 5001")
    
    # Boucle principale
    while True:
        try:
            progress = monitor_progress()
            
            # Vérifier s'il y a des images non taguées
            untagged_count = db.images.count_documents({"tagged": {"$ne": True}})
            pending_tagging_tasks = db.tagging_tasks.count_documents({"status": "pending"})
            
            # Si des images non taguées existent et aucune tâche de tagging n'est en attente
            if untagged_count > 0 and pending_tagging_tasks == 0:
                logger.info(f"Trouvé {untagged_count} images non taguées sans tâche en attente. Création de nouvelles tâches.")
                distribute_tagging_tasks()
            
            # Vérifier s'il y a suffisamment d'images taguées pour la recommandation
            if progress["tagging_complete"]:
                tagged_count = db.images.count_documents({"tagged": True})
                pending_recommendation_tasks = db.recommendation_tasks.count_documents({"status": "pending"})
                
                if tagged_count >= 5 and pending_recommendation_tasks == 0:  # Seuil réduit pour les tests
                    trigger_recommendations()
            
            # Attendre avant la prochaine vérification
            time.sleep(15)  # Diminution du temps d'attente pour une réactivité accrue
        
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
