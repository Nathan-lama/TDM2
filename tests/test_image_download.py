from pymongo import MongoClient
import uuid
import time

# Modifier la connexion MongoDB pour utiliser le bon host
client = MongoClient('mongodb://localhost:27017/')
db = client.imagesdb

def create_test_batch(num_images):
    """Crée un lot de test avec des images Picsum valides"""
    # Nettoyer la base d'abord
    result = db.download_tasks.delete_many({})
    print(f"\nNettoyage: {result.deleted_count} tâches supprimées")
    db.images.delete_many({})
    
    # Créer des URLs Picsum valides (format fixe)
    urls = [f"https://picsum.photos/id/{i}/800/600" for i in range(num_images)]
    print(f"\nTest avec {num_images} images:")
    
    # Calculer le nombre de workers nécessaires
    IMAGES_PER_WORKER = 20
    worker_count = (len(urls) + IMAGES_PER_WORKER - 1) // IMAGES_PER_WORKER
    print(f"Nombre de workers calculé: {worker_count}")
    
    # Répartir les URLs
    base_urls_per_worker = len(urls) // worker_count
    extra_urls = len(urls) % worker_count
    
    # Créer les tâches
    start_idx = 0
    for worker_id in range(1, worker_count + 1):
        worker_urls_count = base_urls_per_worker + (1 if worker_id <= extra_urls else 0)
        worker_urls = urls[start_idx:start_idx + worker_urls_count]
        start_idx += worker_urls_count
        
        task_id = str(uuid.uuid4())
        db.download_tasks.insert_one({
            "_id": task_id,
            "worker_id": worker_id,
            "urls": worker_urls,
            "status": "pending",
            "created_at": time.time()
        })
        print(f"Worker {worker_id}: {len(worker_urls)} images")

def monitor_tasks():
    """Affiche le statut des tâches"""
    print("\nStatut des tâches:")
    tasks = list(db.download_tasks.find())
    for task in tasks:
        print(f"Worker {task['worker_id']}: {len(task['urls'])} URLs, status: {task['status']}")
        if task.get('success_count'):
            print(f"  Images téléchargées: {task['success_count']}/{task.get('total_count', len(task['urls']))}")
    print("-" * 50)

def verify_tasks():
    """Vérifie que les tâches sont bien créées dans MongoDB"""
    tasks = list(db.download_tasks.find())
    if not tasks:
        print("ERREUR: Aucune tâche trouvée dans MongoDB")
        return False
        
    for task in tasks:
        print(f"Tâche {task['_id']}: {len(task['urls'])} URLs, Worker {task['worker_id']}")
    return True

if __name__ == "__main__":
    # Vérifier la connexion à MongoDB
    try:
        client.admin.command('ping')
        print("✓ Connecté à MongoDB")
    except Exception as e:
        print(f"❌ Erreur de connexion MongoDB: {e}")
        exit(1)

    # Tester différents scénarios
    test_cases = [45, 20, 35, 62]
    for num_images in test_cases:
        create_test_batch(num_images)
        time.sleep(2)  # Attendre un peu entre chaque test
        monitor_tasks()

    # Vérifier les résultats à la fin
    print("\nVérification finale des tâches dans MongoDB:")
    verify_tasks()
