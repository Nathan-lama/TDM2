"""
Script utilitaire pour vérifier l'état du système de recommandation
et débloquer les tâches coincées
"""
import time
import pymongo
import os
import datetime
import argparse

# Connexion à MongoDB
DB_URL = os.environ.get('DATABASE_URL', 'mongodb://localhost:27017/imagesdb')
client = pymongo.MongoClient(DB_URL)
db = client.get_database()

def show_tasks():
    """Affiche l'état des tâches de recommandation"""
    tasks = list(db.recommendation_tasks.find().sort('created_at', -1).limit(5))
    
    if not tasks:
        print("Aucune tâche de recommandation trouvée.")
        return
    
    print("\n=== TÂCHES DE RECOMMANDATION ===")
    for task in tasks:
        status = task.get('status', 'unknown')
        created_at = datetime.datetime.fromtimestamp(task.get('created_at', 0))
        user_ids = task.get('user_ids', [])
        
        print(f"ID: {task['_id']}")
        print(f"Status: {status}")
        print(f"Créée le: {created_at}")
        print(f"Utilisateurs: {', '.join(user_ids[:3])}")
        
        if 'started_at' in task:
            started_at = datetime.datetime.fromtimestamp(task['started_at'])
            print(f"Démarrée le: {started_at}")
            
        if 'completed_at' in task:
            completed_at = datetime.datetime.fromtimestamp(task['completed_at'])
            print(f"Terminée le: {completed_at}")
            
        print("---")

def reset_tasks():
    """Réinitialise les tâches bloquées"""
    stuck_tasks = list(db.recommendation_tasks.find({
        "status": "in_progress", 
        "started_at": {"$lt": time.time() - 300}  # Bloquée depuis 5+ minutes
    }))
    
    if not stuck_tasks:
        print("Aucune tâche bloquée trouvée.")
        return
    
    print(f"Réinitialisation de {len(stuck_tasks)} tâches bloquées...")
    
    for task in stuck_tasks:
        db.recommendation_tasks.update_one(
            {"_id": task["_id"]},
            {"$set": {"status": "pending"}}
        )
        print(f"Tâche {task['_id']} réinitialisée.")

def show_recommendations():
    """Affiche des statistiques sur les recommandations générées"""
    recs = list(db.recommendations.find())
    
    if not recs:
        print("Aucune recommandation trouvée.")
        return
    
    print(f"\n=== RECOMMANDATIONS ({len(recs)} utilisateurs) ===")
    
    for rec in recs:
        user_id = rec.get('user_id', 'unknown')
        recommendations = rec.get('recommendations', [])
        generated_at = "N/A"
        
        if 'generated_at' in rec:
            generated_at = datetime.datetime.fromtimestamp(rec['generated_at'])
        
        print(f"Utilisateur: {user_id}")
        print(f"Recommandations: {len(recommendations)}")
        print(f"Générées le: {generated_at}")
        print("---")

def main():
    parser = argparse.ArgumentParser(description="Outil de débogage pour le système de recommandation")
    parser.add_argument('--reset', action='store_true', help="Réinitialiser les tâches bloquées")
    args = parser.parse_args()
    
    # Afficher l'état des tâches
    show_tasks()
    show_recommendations()
    
    # Réinitialiser les tâches si demandé
    if args.reset:
        reset_tasks()

if __name__ == "__main__":
    main()
