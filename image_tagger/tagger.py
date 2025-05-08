import os
import time
import logging
import json
from pymongo import MongoClient
from pyspark.sql import SparkSession
from PIL import Image
import numpy as np
import cv2
from sklearn.cluster import KMeans
import colorsys
import traceback

# Configuration du logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('image_tagger')

# ID du worker (attribué par docker-compose)
WORKER_ID = int(os.environ.get('WORKER_ID', 1))
logger.info(f"Démarrage du tagger d'images (Worker ID: {WORKER_ID})")

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL')
client = MongoClient(DB_URL)
db = client.get_database()

# Configuration Spark - on continue d'utiliser PySpark comme demandé
spark = SparkSession.builder \
    .appName(f"ImageTagger-{WORKER_ID}") \
    .config("spark.driver.memory", "1g") \
    .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer") \
    .config("spark.kryoserializer.buffer.max", "512m") \
    .config("spark.executor.heartbeatInterval", "20s") \
    .getOrCreate()

def rgb_to_hex(rgb):
    """Convertit un triplet RGB en valeur hexadécimale - version sérialisable"""
    r = int(rgb[0])
    g = int(rgb[1])
    b = int(rgb[2])
    return f'#{r:02x}{g:02x}{b:02x}'

def extract_color_name(r, g, b):
    """Version simplifiée et sérialisable (pas de tableaux NumPy)"""
    r_norm, g_norm, b_norm = r/255.0, g/255.0, b/255.0
    h, s, v = colorsys.rgb_to_hsv(r_norm, g_norm, b_norm)
    
    if v < 0.2:
        return "noir"
    if v > 0.8 and s < 0.2:
        return "blanc"
    if s < 0.2:
        return "gris"
    
    # Classification par angle de teinte (en degrés)
    h_deg = h * 360
    
    if h_deg < 30 or h_deg >= 330:
        return "rouge"
    elif h_deg < 90:
        return "jaune"
    elif h_deg < 150:
        return "vert"
    elif h_deg < 210:
        return "cyan"
    elif h_deg < 270:
        return "bleu"
    else:
        return "magenta"

def tag_image_simple(image_id):
    """Fonction map pour PySpark - contient toute la logique sans dépendances externes"""
    try:
        # Construire le chemin de l'image
        img_path = f"/data/images/{image_id}.jpg"
        
        if not os.path.exists(img_path):
            return (False, {"image_id": image_id, "error": f"Fichier introuvable: {img_path}"})
        
        # Charger l'image avec PIL pour les métadonnées de base
        try:
            pil_image = Image.open(img_path)
            width, height = pil_image.size
            format_img = pil_image.format
            mode = pil_image.mode
        except Exception as e:
            return (False, {"image_id": image_id, "error": f"Erreur PIL: {e}"})
        
        # Charger avec OpenCV pour l'analyse avancée
        try:
            cv_image = cv2.imread(img_path)
            if cv_image is None:
                return (False, {"image_id": image_id, "error": "Impossible de lire l'image avec OpenCV"})
        except Exception as e:
            return (False, {"image_id": image_id, "error": f"Erreur OpenCV: {e}"})
        
        # Extraire des tags basiques - avec des valeurs scalaires
        image_tags = []
        
        # Orientation
        aspect_ratio = float(width) / float(height) if height > 0 else 1.0
        if aspect_ratio > 1.2:
            orientation = "paysage"
            image_tags.append("paysage")
        elif aspect_ratio < 0.8:
            orientation = "portrait"
            image_tags.append("portrait")
        else:
            orientation = "carré"
            image_tags.append("carré")
        
        # Taille
        pixel_count = int(width * height)
        if pixel_count < 250000:
            image_tags.append("petite image")
        elif pixel_count > 1000000:
            image_tags.append("grande image")
        else:
            image_tags.append("image moyenne")
        
        # Luminosité moyenne (si OpenCV réussit)
        brightness = 0
        sharpness = 0
        
        if cv_image is not None:
            try:
                # Convertir en niveau de gris
                gray_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
                
                # Calculer la luminosité moyenne (en tant que scalaire)
                brightness = float(np.mean(gray_image))
                
                if brightness < 85:
                    image_tags.append("sombre")
                elif brightness > 170:
                    image_tags.append("claire")
                else:
                    image_tags.append("luminosité moyenne")
                
                # Netteté (variance du Laplacien)
                laplacian_var = cv2.Laplacian(gray_image, cv2.CV_64F).var()
                sharpness = float(laplacian_var)  # Convertir en float simple
                
                if sharpness < 100:
                    image_tags.append("flou")
                else:
                    image_tags.append("net")
            except Exception as e:
                # En cas d'erreur, continuer sans ces tags
                pass
        
        # Extraction des couleurs dominantes
        dominant_colors = []
        try:
            # Redimensionner l'image pour accélérer le traitement
            small = cv2.resize(cv_image, (50, 50))
            pixels = small.reshape(-1, 3)
            
            # Utiliser KMeans avec un faible nombre de clusters pour plus de rapidité
            kmeans = KMeans(n_clusters=3, random_state=42, n_init=1)
            kmeans.fit(pixels)
            
            # Récupérer les centres (ce sont des tableaux NumPy)
            centers = kmeans.cluster_centers_
            
            # Les convertir en valeurs primitives pour la sérialisation
            for i, center in enumerate(centers):
                r, g, b = int(center[0]), int(center[1]), int(center[2])
                hex_color = rgb_to_hex([r, g, b])
                name = extract_color_name(r, g, b)
                
                # Calculer le pourcentage (nombre de pixels de ce cluster / total)
                labels = kmeans.labels_
                count = np.sum(labels == i)
                percentage = float(count) / len(labels) * 100
                
                dominant_colors.append({
                    "hex": hex_color,
                    "name": name,
                    "rgb": [r, g, b],  # Liste Python standard, pas de tableau NumPy
                    "percentage": round(float(percentage), 2)  # Convertir en float standard
                })
                
                # Ajouter la couleur comme tag si elle est significative
                if percentage > 20:
                    image_tags.append(f"couleur:{name}")
        except Exception as e:
            # Si l'extraction des couleurs échoue, continuer sans couleurs
            pass
        
        # Mode couleur
        if mode == "L":
            image_tags.append("noir et blanc")
        else:
            image_tags.append("couleur")
        
        # Retourner les métadonnées à stocker
        metadata = {
            "image_id": image_id,
            "dominant_colors": dominant_colors,
            "tags": image_tags,
            "orientation": orientation,
            "brightness": brightness,
            "sharpness": sharpness,
            "aspect_ratio": round(aspect_ratio, 2)
        }
        
        return (True, metadata)
    except Exception as e:
        # Capture toute exception non prévue
        return (False, {"image_id": image_id, "error": str(e)})

def process_task():
    """Traite les tâches de tagging attribuées à ce worker"""
    task = db.tagging_tasks.find_one({"worker_id": WORKER_ID, "status": "pending"})
    
    if not task:
        logger.info(f"Aucune tâche trouvée pour le Worker {WORKER_ID}")
        return False
    
    # Marquer la tâche comme en cours
    db.tagging_tasks.update_one(
        {"_id": task["_id"]},
        {"$set": {"status": "in_progress", "started_at": time.time()}}
    )
    
    image_ids = task.get("image_ids", [])
    if not image_ids:
        logger.warning(f"Tâche trouvée pour le Worker {WORKER_ID} mais sans images")
        # Marquer comme terminée si vide
        db.tagging_tasks.update_one(
            {"_id": task["_id"]},
            {"$set": {"status": "completed", "completed_at": time.time(), "success_count": 0, "total_count": 0}}
        )
        return False
    
    logger.info(f"Traitement de {len(image_ids)} images pour le Worker {WORKER_ID}")
    
    # Traiter les images par petits lots pour éviter les problèmes de mémoire
    batch_size = min(10, len(image_ids))
    success_count = 0
    
    for i in range(0, len(image_ids), batch_size):
        batch = image_ids[i:i+batch_size]
        logger.info(f"Traitement du lot {i//batch_size + 1}/{(len(image_ids)-1)//batch_size + 1} ({len(batch)} images)")
        
        # Utilisation de PySpark pour le parallélisme
        image_ids_rdd = spark.sparkContext.parallelize(batch)
        results = image_ids_rdd.map(tag_image_simple).collect()
        
        # Traiter les résultats hors du contexte Spark
        for success, data in results:
            if success:
                metadata = data
                image_id = metadata["image_id"]
                
                # Mettre à jour l'image avec les métadonnées
                db.images.update_one(
                    {"_id": image_id},
                    {"$set": {
                        "dominant_colors": metadata["dominant_colors"],
                        "tags": metadata["tags"],
                        "orientation": metadata["orientation"],
                        "brightness": metadata["brightness"],
                        "sharpness": metadata["sharpness"],
                        "aspect_ratio": metadata["aspect_ratio"],
                        "tagged": True,
                        "tagged_at": time.time(),
                        "tagged_by": f"worker_{WORKER_ID}"
                    }}
                )
                
                # Mettre à jour les tags
                for tag in metadata["tags"]:
                    db.tags.update_one(
                        {"name": tag},
                        {"$addToSet": {"image_ids": image_id}},
                        upsert=True
                    )
                
                logger.info(f"Image taguée: {image_id}")
                success_count += 1
            else:
                error_data = data
                logger.error(f"Échec du tagging de {error_data['image_id']}: {error_data.get('error', 'Erreur inconnue')}")
        
        # Mettre à jour la progression
        progress = min(100, int((i + len(batch)) / len(image_ids) * 100))
        db.tagging_tasks.update_one(
            {"_id": task["_id"]},
            {"$set": {
                "progress": progress,
                "current_success": success_count
            }}
        )
    
    # Mettre à jour le statut final de la tâche
    db.tagging_tasks.update_one(
        {"_id": task["_id"]},
        {"$set": {
            "status": "completed",
            "completed_at": time.time(),
            "success_count": success_count,
            "total_count": len(image_ids)
        }}
    )
    
    logger.info(f"Tâche complétée: {success_count}/{len(image_ids)} images taguées avec succès")
    return True

def main():
    """Fonction principale du tagger d'images"""
    while True:
        try:
            task_processed = process_task()
            
            if not task_processed:
                # Pas de tâche, attendre un peu plus longtemps
                logger.info("En attente de nouvelles tâches...")
                time.sleep(10)  # Réduit pour plus de réactivité
            else:
                # Tâche traitée, vérifier rapidement s'il y en a d'autres
                time.sleep(2)
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}")
            traceback.print_exc()
            time.sleep(15)  # Attendre avant de réessayer

if __name__ == "__main__":
    main()
