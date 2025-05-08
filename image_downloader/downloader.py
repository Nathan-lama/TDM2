import os
import requests
import time
import logging
import json
from pymongo import MongoClient
from pyspark.sql import SparkSession
from PIL import Image
from io import BytesIO
import hashlib

# Configuration du logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('image_downloader')

# ID du worker (attribué par docker-compose)
WORKER_ID = int(os.environ.get('WORKER_ID', 1))
logger.info(f"Démarrage du téléchargeur d'images (Worker ID: {WORKER_ID})")

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL')
client = MongoClient(DB_URL)
db = client.get_database()

# Configuration Spark
spark = SparkSession.builder \
    .appName(f"ImageDownloader-{WORKER_ID}") \
    .config("spark.driver.memory", "512m") \
    .getOrCreate()

def download_image_simple(url):
    """Version simplifiée qui ne capture pas d'objets non-sérialisables"""
    try:
        # Générer un ID unique basé sur l'URL
        image_id = hashlib.md5(url.encode()).hexdigest()
        
        # Sauvegarder l'image dans le volume partagé
        img_path = f"/data/images/{image_id}.jpg"
        
        # Configuration des headers pour éviter les blocages
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'
        }
        
        # Téléchargement de l'image
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Vérifier que le contenu est bien une image
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            logger.warning(f"Type de contenu non reconnu comme image: {content_type} pour {url}")
        
        # Sauvegarder l'image brute
        with open(img_path, 'wb') as f:
            f.write(response.content)
        
        # Vérifier que l'image est valide en l'ouvrant avec PIL
        img = Image.open(img_path)
        # Force conversion to RGB if necessary
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
            img.save(img_path)
        
        # Récupérer les métadonnées sans MongoDB
        metadata = {
            "_id": image_id,
            "url": url,
            "path": img_path,
            "format": img.format,
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "orientation": "landscape" if img.width > img.height else 
                          "portrait" if img.height > img.width else "square",
            "size_bytes": len(response.content),
            "downloaded_at": time.time(),
            "downloaded_by": f"worker_{WORKER_ID}",
            "tagged": False,
            "source": "wikidata"
        }
        
        logger.info(f"Image téléchargée avec succès: {url} -> {img_path}")
        return (True, metadata)
        
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement de {url}: {e}")
        # Nettoyer les fichiers partiels en cas d'erreur
        if 'img_path' in locals() and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except:
                pass
        return (False, {"url": url, "error": str(e)})

def clean_database():
    """Nettoie la base de données des anciennes images et tâches"""
    try:
        # Supprimer toutes les images existantes de la base de données
        image_count = db.images.count_documents({})
        db.images.delete_many({})
        logger.info(f"Supprimé {image_count} images de la base de données")
        
        # Supprimer les anciennes tâches
        task_count = db.download_tasks.count_documents({})
        db.download_tasks.delete_many({})
        logger.info(f"Supprimé {task_count} tâches de téléchargement")
        
        # Supprimer les tags et recommandations
        db.tags.delete_many({})
        db.tagging_tasks.delete_many({})
        db.recommendation_tasks.delete_many({})
        db.recommendations.delete_many({})
        
        # Nettoyer le dossier d'images
        image_dir = "/data/images"
        if os.path.exists(image_dir):
            for filename in os.listdir(image_dir):
                file_path = os.path.join(image_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression du fichier {file_path}: {e}")
        
        return True
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage de la base de données: {e}")
        return False

def process_task():
    """Traite les tâches de téléchargement attribuées à ce worker"""
    # Vérifie s'il y a une tâche de nettoyage
    clean_task = db.download_tasks.find_one({"worker_id": WORKER_ID, "action": "clean", "status": "pending"})
    if clean_task:
        logger.info("Tâche de nettoyage détectée. Nettoyage de la base de données...")
        success = clean_database()
        db.download_tasks.update_one(
            {"_id": clean_task["_id"]},
            {"$set": {
                "status": "completed" if success else "failed",
                "completed_at": time.time()
            }}
        )
        return True
    
    # Traitement normal des tâches de téléchargement
    task = db.download_tasks.find_one({"worker_id": WORKER_ID, "status": "pending"})
    
    if not task:
        logger.info(f"Aucune tâche trouvée pour le Worker {WORKER_ID}")
        return False
    
    urls = task.get("urls", [])
    if not urls:
        logger.warning(f"Tâche trouvée pour le Worker {WORKER_ID} mais sans URLs")
        return False
    
    logger.info(f"Traitement de {len(urls)} URLs pour le Worker {WORKER_ID}")
    
    # Utilisation de PySpark pour traiter les URLs
    urls_rdd = spark.sparkContext.parallelize(urls)
    
    # Utilisation d'une fonction qui ne capture pas d'objets non-sérialisables
    results = urls_rdd.map(download_image_simple).collect()
    
    # Traiter les résultats après que Spark a fait son travail
    success_count = 0
    for success, metadata in results:
        if success:
            # Maintenant nous pouvons utiliser MongoDB en toute sécurité
            db.images.update_one(
                {"_id": metadata["_id"]},
                {"$set": metadata},
                upsert=True
            )
            success_count += 1
        else:
            logger.error(f"Erreur lors du téléchargement de {metadata['url']}: {metadata.get('error')}")
    
    # Mettre à jour le statut de la tâche
    db.download_tasks.update_one(
        {"_id": task["_id"]},
        {"$set": {
            "status": "completed",
            "completed_at": time.time(),
            "success_count": success_count,
            "total_count": len(urls)
        }}
    )
    
    logger.info(f"Tâche complétée: {success_count}/{len(urls)} images téléchargées avec succès")
    return True

def main():
    """Fonction principale du téléchargeur d'images"""
    while True:
        task_processed = process_task()
        
        if not task_processed:
            # Pas de tâche, attendre un peu plus longtemps
            logger.info("En attente de nouvelles tâches...")
            time.sleep(60)
        else:
            # Tâche traitée, vérifier rapidement s'il y en a d'autres
            time.sleep(5)

if __name__ == "__main__":
    main()
