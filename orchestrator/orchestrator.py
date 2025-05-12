from pymongo import MongoClient
import time
import json
import os
import logging
import requests
from pyspark.sql import SparkSession

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

def distribute_download_tasks():
    """Distribue les tâches de téléchargement aux instances image_downloader"""
    image_sources = load_image_sources()
    
    # Utilisation de map-reduce avec lambda pour préparer les tâches
    # Map: Associer un ID de worker à chaque URL
    worker_assignments = list(map(lambda i: (i[0] % 2 + 1, i[1]), enumerate(image_sources)))
    
    # Reduce: Grouper par worker_id
    tasks_by_worker = {}
    for worker_id, url in worker_assignments:
        if worker_id not in tasks_by_worker:
            tasks_by_worker[worker_id] = []
        tasks_by_worker[worker_id].append(url)
    
    # Sauvegarder les tâches dans la base de données
    for worker_id, urls in tasks_by_worker.items():
        db.download_tasks.update_one(
            {"worker_id": worker_id},
            {"$set": {"urls": urls, "status": "pending"}},
            upsert=True
        )
    
    logger.info(f"Tâches de téléchargement distribuées: {len(image_sources)} URLs")

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
    
    # Diviser les IDs en deux groupes pour les deux workers
    half = len(image_ids) // 2
    worker1_ids = image_ids[:half + (1 if len(image_ids) % 2 == 1 else 0)]
    worker2_ids = image_ids[half + (1 if len(image_ids) % 2 == 1 else 0):]
    
    # Créer une tâche pour le worker 1 s'il y a des images
    if worker1_ids:
        db.tagging_tasks.insert_one({
            "_id": str(time.time()) + "_1",
            "worker_id": 1,
            "image_ids": worker1_ids,
            "status": "pending",
            "created_at": time.time()
        })
    
    # Créer une tâche pour le worker 2 s'il y a des images
    if worker2_ids:
        db.tagging_tasks.insert_one({
            "_id": str(time.time()) + "_2",
            "worker_id": 2,
            "image_ids": worker2_ids,
            "status": "pending",
            "created_at": time.time()
        })
    
    logger.info(f"Tâches de tagging créées: {len(worker1_ids)} images pour worker 1 et {len(worker2_ids)} images pour worker 2")
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
    
    # Distribuer les tâches initiales
    # Pour le démarrage, on ne distribue pas automatiquement des tâches de téléchargement
    # car cela sera fait via l'interface utilisateur
    
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
