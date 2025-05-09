from pymongo import MongoClient
import os

def clean_database():
    """Nettoie complètement la base de données et les fichiers"""
    try:
        # Connexion à MongoDB
        client = MongoClient('mongodb://localhost:27017/')
        db = client.imagesdb
        
        print("Nettoyage de la base de données...")
        
        # Supprimer toutes les collections
        collections = [
            'images', 
            'download_tasks', 
            'tagging_tasks', 
            'tags', 
            'recommendations'
        ]
        
        for collection in collections:
            count = db[collection].count_documents({})
            result = db[collection].delete_many({})
            print(f"Collection {collection}: {count} documents supprimés")
        
        print("\nBase de données nettoyée avec succès!")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"Erreur lors du nettoyage: {e}")
        return False

if __name__ == "__main__":
    clean_database()
