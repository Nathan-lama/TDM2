import subprocess
import time
from pymongo import MongoClient
import uuid

# Connexion MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client.imagesdb

def scale_workers(count):
    """Change le nombre de workers"""
    cmd = f"docker-compose up -d --scale image_downloader={count}"
    print(f"\nExécution: {cmd}")
    subprocess.run(cmd, shell=True)
    time.sleep(5)  # Attendre que les conteneurs démarrent

def create_download_task(urls, worker_id):
    """Crée une tâche de téléchargement"""
    task_id = str(uuid.uuid4())
    db.download_tasks.insert_one({
        "_id": task_id,
        "worker_id": worker_id,
        "urls": urls,
        "status": "pending",
        "created_at": time.time()
    })
    return task_id

def test_scaling_scenario():
    """Test complet du scaling et de la distribution"""
    # 1. Nettoyer la base de données
    db.download_tasks.delete_many({})
    db.images.delete_many({})
    
    # 2. Créer une liste d'URLs de test
    urls = [f"https://picsum.photos/id/{i}/800/600" for i in range(50)]
    print(f"\nTest avec {len(urls)} images")

    # 3. Tester différentes configurations de scaling
    for worker_count in [2, 3, 4]:
        print(f"\n=== Test avec {worker_count} workers ===")
        
        # Scaler les workers
        scale_workers(worker_count)
        
        # Distribuer les URLs
        urls_per_worker = len(urls) // worker_count
        extra_urls = len(urls) % worker_count
        
        start_idx = 0
        for worker_id in range(1, worker_count + 1):
            # Calculer les URLs pour ce worker
            worker_urls_count = urls_per_worker + (1 if worker_id <= extra_urls else 0)
            worker_urls = urls[start_idx:start_idx + worker_urls_count]
            start_idx += worker_urls_count
            
            # Créer la tâche
            task_id = create_download_task(worker_urls, worker_id)
            print(f"Worker {worker_id}: {len(worker_urls)} URLs (Task: {task_id})")
        
        # Attendre et vérifier le progrès
        time.sleep(10)
        completed = db.download_tasks.count_documents({"status": "completed"})
        print(f"Tâches complétées: {completed}/{worker_count}")

if __name__ == "__main__":
    test_scaling_scenario()
