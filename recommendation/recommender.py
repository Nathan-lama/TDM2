import os
import time
import logging
import json
from pymongo import MongoClient
import numpy as np
from pyspark.sql import SparkSession
from collections import Counter
import traceback

# Configuration du logger
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('recommender')

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL')
client = MongoClient(DB_URL)
db = client.get_database()

# Configuration de Spark avec des paramètres optimisés
spark = SparkSession.builder \
    .appName("ImageRecommendationSystem") \
    .config("spark.driver.memory", "1g") \
    .config("spark.executor.memory", "1g") \
    .config("spark.driver.extraJavaOptions", "-XX:+UseG1GC") \
    .getOrCreate()

# Réduire le niveau de verbosité de Spark
spark.sparkContext.setLogLevel("WARN")
logger.info("Session Spark initialisée avec succès")

def get_user_preferences(user_id):
    """Récupère les préférences d'un utilisateur basées sur ses likes"""
    try:
        # Récupérer tous les likes de l'utilisateur
        likes = list(db.user_likes.find({"user_id": user_id, "liked": True}))
        liked_image_ids = [like["image_id"] for like in likes]
        
        if len(liked_image_ids) < 5:
            logger.info(f"L'utilisateur {user_id} n'a pas assez de likes ({len(liked_image_ids)}/5)")
            return None
            
        # Récupérer les informations sur les images aimées
        liked_images = list(db.images.find({"_id": {"$in": liked_image_ids}}))
        logger.info(f"Récupéré {len(liked_images)} images aimées pour {user_id}")
        
        # Extraire les tags préférés
        all_tags = []
        for image in liked_images:
            if "tags" in image and image["tags"]:
                all_tags.extend(image["tags"])
        
        tag_counts = Counter(all_tags)
        favorite_tags = [tag for tag, count in tag_counts.most_common(10)]
        
        # Extraire les couleurs préférées
        all_colors = []
        for image in liked_images:
            if "dominant_colors" in image:
                for color in image["dominant_colors"]:
                    if "name" in color:
                        all_colors.append(color["name"])
        
        color_counts = Counter(all_colors)
        favorite_colors = [color for color, count in color_counts.most_common(5)]
        
        # Construire le profil de préférences
        preferences = {
            "liked_images": liked_image_ids,
            "favorite_tags": favorite_tags,
            "favorite_colors": favorite_colors,
            "orientation": get_preferred_orientation(liked_images)
        }
        
        logger.info(f"Préférences pour {user_id}: {len(favorite_tags)} tags, {len(favorite_colors)} couleurs")
        return preferences
        
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction des préférences: {e}")
        traceback.print_exc()
        return None

def get_preferred_orientation(images):
    """Détermine l'orientation préférée (paysage, portrait, carré)"""
    orientations = [img.get("orientation", "unknown") for img in images if "orientation" in img]
    if not orientations:
        return None
    return Counter(orientations).most_common(1)[0][0]

def calculate_image_score(image, preferences):
    """Calcule un score de similarité entre une image et les préférences utilisateur"""
    if not preferences or not image:
        return 0
    
    # Ne pas recommander les images déjà aimées
    if image["_id"] in preferences["liked_images"]:
        return 0
    
    score = 0
    
    # Score basé sur les tags (max 50 points)
    if "tags" in image and image["tags"]:
        for tag in image["tags"]:
            if tag in preferences["favorite_tags"]:
                score += 10  # 10 points par tag correspondant
    
    # Score basé sur les couleurs (max 30 points)
    if "dominant_colors" in image:
        for color in image["dominant_colors"]:
            if "name" in color and color["name"] in preferences["favorite_colors"]:
                score += 6  # 6 points par couleur correspondante
    
    # Score basé sur l'orientation (max 20 points)
    if preferences["orientation"] and "orientation" in image:
        if image["orientation"] == preferences["orientation"]:
            score += 20  # Bonus pour l'orientation préférée
    
    return score

def generate_recommendations_for_user(user_id):
    """Génère des recommandations d'images pour un utilisateur"""
    try:
        logger.info(f"Génération de recommandations pour {user_id}")
        
        # Récupérer les préférences de l'utilisateur
        preferences = get_user_preferences(user_id)
        if not preferences:
            logger.warning(f"Impossible de générer des recommandations pour {user_id}: pas assez de likes")
            return []
        
        # Récupérer toutes les images taguées
        all_tagged_images = list(db.images.find({"tagged": True}))
        logger.info(f"Analyse de {len(all_tagged_images)} images taguées")
        
        if not all_tagged_images:
            return []
        
        # Utiliser Spark pour le calcul parallèle des scores
        try:
            # Convertir les images en RDD
            images_rdd = spark.sparkContext.parallelize(all_tagged_images)
            
            # Calculer les scores pour chaque image (broadcast des préférences)
            prefs_broadcast = spark.sparkContext.broadcast(preferences)
            scored_images = images_rdd.map(
                lambda img: (img["_id"], calculate_image_score(img, prefs_broadcast.value), img)
            ).filter(lambda x: x[1] > 0)  # Filtrer les scores > 0
            
            # Collecter et trier les résultats
            results = scored_images.collect()
            results.sort(key=lambda x: x[1], reverse=True)
            
            # Prendre les 20 meilleures recommandations
            top_recommendations = results[:20]
            
            recommendations = []
            for image_id, score, image in top_recommendations:
                recommendations.append({
                    "image_id": image_id,
                    "score": score,
                    "tags": image.get("tags", []),
                    "colors": [c["name"] for c in image.get("dominant_colors", []) if "name" in c]
                })
            
            logger.info(f"Générées {len(recommendations)} recommandations pour {user_id}")
            return recommendations
            
        except Exception as spark_error:
            logger.error(f"Erreur Spark: {spark_error} - Utilisation d'une alternative sans Spark")
            
            # Alternative sans Spark (fallback)
            recommendations = []
            for image in all_tagged_images:
                score = calculate_image_score(image, preferences)
                if score > 0:
                    recommendations.append({
                        "image_id": image["_id"],
                        "score": score,
                        "tags": image.get("tags", []),
                        "colors": [c["name"] for c in image.get("dominant_colors", []) if "name" in c]
                    })
            
            # Trier par score et limiter à 20
            recommendations.sort(key=lambda x: x["score"], reverse=True)
            return recommendations[:20]
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération des recommandations: {e}")
        traceback.print_exc()
        return []

def process_recommendation_tasks():
    """Traite les tâches de recommandation en attente"""
    try:
        # Rechercher une tâche en attente
        task = db.recommendation_tasks.find_one({"status": "pending"})
        
        if not task:
            return False
        
        # Marquer la tâche comme en cours
        db.recommendation_tasks.update_one(
            {"_id": task["_id"]},
            {"$set": {"status": "in_progress", "started_at": time.time()}}
        )
        
        logger.info(f"Traitement de la tâche {task['_id']}")
        
        # Récupérer les utilisateurs pour lesquels générer des recommandations
        user_ids = task.get("user_ids", [])
        if not user_ids:
            logger.warning("Tâche sans utilisateurs")
            db.recommendation_tasks.update_one(
                {"_id": task["_id"]},
                {"$set": {"status": "completed", "completed_at": time.time()}}
            )
            return False
        
        # Générer des recommandations pour chaque utilisateur
        for user_id in user_ids:
            recommendations = generate_recommendations_for_user(user_id)
            
            # Stocker les recommandations dans MongoDB
            db.recommendations.update_one(
                {"user_id": user_id},
                {"$set": {
                    "recommendations": recommendations,
                    "generated_at": time.time()
                }},
                upsert=True
            )
        
        # Marquer la tâche comme terminée
        db.recommendation_tasks.update_one(
            {"_id": task["_id"]},
            {"$set": {"status": "completed", "completed_at": time.time()}}
        )
        
        logger.info(f"Tâche {task['_id']} traitée avec succès")
        return True
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la tâche: {e}")
        if 'task' in locals() and task:
            # Marquer la tâche comme échouée
            db.recommendation_tasks.update_one(
                {"_id": task["_id"]},
                {"$set": {"status": "failed", "error": str(e), "completed_at": time.time()}}
            )
        return False

def main():
    """Boucle principale du système de recommandation"""
    logger.info("Système de recommandation démarré")
    
    while True:
        try:
            task_processed = process_recommendation_tasks()
            
            if task_processed:
                # Si une tâche a été traitée, vérifier immédiatement s'il y en a d'autres
                time.sleep(1)
            else:
                # Sinon, attendre un peu avant de vérifier à nouveau
                time.sleep(5)
                
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}")
            time.sleep(30)  # Attendre plus longtemps en cas d'erreur

if __name__ == "__main__":
    main()
