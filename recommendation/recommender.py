import os
import time
import logging
import json
from pymongo import MongoClient
from pyspark.sql import SparkSession
from pyspark.ml.feature import StringIndexer, OneHotEncoder, VectorAssembler
from pyspark.ml.recommendation import ALS
import numpy as np
from collections import Counter

# Configuration du logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('recommender')

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL')
client = MongoClient(DB_URL)
db = client.get_database()

# Configuration Spark
spark = SparkSession.builder \
    .appName("ImageRecommender") \
    .config("spark.driver.memory", "2g") \
    .getOrCreate()

def get_user_preferences(user_id):
    """Récupère les préférences d'un utilisateur"""
    user = db.users.find_one({"_id": user_id})
    if not user:
        return None
    
    # Récupérer les likes/dislikes de l'utilisateur
    likes = list(db.user_likes.find({"user_id": user_id, "liked": True}))
    dislikes = list(db.user_likes.find({"user_id": user_id, "liked": False}))
    
    # Extraire les IDs des images
    liked_image_ids = [like["image_id"] for like in likes]
    disliked_image_ids = [dislike["image_id"] for dislike in dislikes]
    
    # Récupérer les caractéristiques des images aimées
    liked_images = list(db.images.find({"_id": {"$in": liked_image_ids}}))
    
    # Extraire les tags préférés
    all_tags = []
    for image in liked_images:
        if "tags" in image:
            all_tags.extend(image["tags"])
    
    # Compter les occurrences de chaque tag
    tag_counts = Counter(all_tags)
    favorite_tags = [tag for tag, count in tag_counts.most_common(10)]
    
    # Extraire les couleurs préférées
    all_colors = []
    for image in liked_images:
        if "dominant_colors" in image:
            for color in image["dominant_colors"]:
                all_colors.append(color["name"])
    
    # Compter les occurrences de chaque couleur
    color_counts = Counter(all_colors)
    favorite_colors = [color for color, count in color_counts.most_common(5)]
    
    # Retourner le profil de préférences
    return {
        "user_id": user_id,
        "liked_images": liked_image_ids,
        "disliked_images": disliked_image_ids,
        "favorite_tags": favorite_tags,
        "favorite_colors": favorite_colors
    }

def calculate_image_score(image, user_prefs):
    """Calcule un score pour une image en fonction des préférences de l'utilisateur"""
    score = 0
    
    # Éviter les images déjà vues
    if image["_id"] in user_prefs["liked_images"] or image["_id"] in user_prefs["disliked_images"]:
        return -1  # Ne pas recommander les images déjà vues
    
    # Score basé sur les tags
    if "tags" in image:
        for tag in image["tags"]:
            if tag in user_prefs["favorite_tags"]:
                score += 1
    
    # Score basé sur les couleurs
    if "dominant_colors" in image:
        for color in image["dominant_colors"]:
            if color["name"] in user_prefs["favorite_colors"]:
                score += 0.5
    
    return score

def generate_recommendations_for_user(user_id):
    """Génère des recommandations pour un utilisateur spécifique"""
    # Récupérer les préférences
    user_prefs = get_user_preferences(user_id)
    if not user_prefs:
        logger.warning(f"Aucune préférence trouvée pour l'utilisateur {user_id}")
        return []
    
    # Récupérer toutes les images taguées
    all_images = list(db.images.find({"tagged": True}))
    
    # Utiliser Spark pour calculer les scores en parallèle
    images_rdd = spark.sparkContext.parallelize(all_images)
    
    # Map: calculer le score pour chaque image
    scored_images_rdd = images_rdd.map(
        lambda img: (img["_id"], calculate_image_score(img, user_prefs), img)
    )
    
    # Filtrer les images avec score négatif (déjà vues)
    positive_scores_rdd = scored_images_rdd.filter(lambda x: x[1] > 0)
    
    # Trier par score décroissant et prendre les 20 meilleures recommandations
    top_recommendations = positive_scores_rdd.sortBy(
        lambda x: x[1], ascending=False
    ).take(20)
    
    # Formater les résultats
    recommendations = []
    for _, score, image in top_recommendations:
        recommendations.append({
            "image_id": image["_id"],
            "score": score,
            "path": image["path"],
            "tags": image.get("tags", []),
            "colors": [c["name"] for c in image.get("dominant_colors", [])]
        })
    
    return recommendations

def process_recommendation_tasks():
    """Traite les tâches de recommandation en attente"""
    task = db.recommendation_tasks.find_one({"status": "pending"})
    
    if not task:
        logger.info("Aucune tâche de recommandation en attente")
        return False
    
    user_ids = task.get("user_ids", [])
    if not user_ids:
        logger.warning("Tâche de recommandation sans utilisateurs")
        return False
    
    logger.info(f"Génération de recommandations pour {len(user_ids)} utilisateurs")
    
    # Utiliser map-reduce avec expressions lambda pour générer les recommandations
    user_ids_rdd = spark.sparkContext.parallelize(user_ids)
    recommendations_by_user = user_ids_rdd.map(
        lambda uid: (uid, generate_recommendations_for_user(uid))
    ).collect()
    
    # Sauvegarder les recommandations
    for user_id, recommendations in recommendations_by_user:
        db.recommendations.update_one(
            {"user_id": user_id},
            {"$set": {
                "recommendations": recommendations,
                "generated_at": time.time()
            }},
            upsert=True
        )
    
    # Mettre à jour le statut de la tâche
    db.recommendation_tasks.update_one(
        {"_id": task["_id"]},
        {"$set": {
            "status": "completed",
            "completed_at": time.time()
        }}
    )
    
    logger.info("Génération de recommandations terminée")
    return True

def main():
    """Fonction principale du système de recommandation"""
    logger.info("Démarrage du système de recommandation")
    
    while True:
        task_processed = process_recommendation_tasks()
        
        if not task_processed:
            # Pas de tâche, attendre un peu plus longtemps
            logger.info("En attente de nouvelles tâches de recommandation...")
            time.sleep(60)
        else:
            # Tâche traitée, vérifier rapidement s'il y en a d'autres
            time.sleep(5)

if __name__ == "__main__":
    main()
