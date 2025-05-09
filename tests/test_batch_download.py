from pymongo import MongoClient
import uuid
import time

# Configuration MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client.imagesdb

def test_batch_download(num_images=45):
    """Test la répartition des images entre les workers"""
    print(f"\nTest de répartition pour {num_images} images:")
    
    # Simuler une liste d'URLs
    urls = [f"https://fake-image-{i}.jpg" for i in range(num_images)]
    
    # Constantes
    IMAGES_PER_WORKER = 20
    
    # Calculer le nombre de workers nécessaires
    worker_count = (len(urls) + IMAGES_PER_WORKER - 1) // IMAGES_PER_WORKER
    print(f"Nombre de workers nécessaires: {worker_count}")
    
    # Calculer la répartition des URLs
    base_urls_per_worker = len(urls) // worker_count
    extra_urls = len(urls) % worker_count
    
    # Créer les tâches
    start_idx = 0
    for worker_id in range(1, worker_count + 1):
        # Calculer le nombre d'URLs pour ce worker
        worker_urls_count = base_urls_per_worker + (1 if worker_id <= extra_urls else 0)
        worker_urls = urls[start_idx:start_idx + worker_urls_count]
        start_idx += worker_urls_count
        
        # Créer la tâche
        task_id = str(uuid.uuid4())
        db.download_tasks.insert_one({
            "_id": task_id,
            "worker_id": worker_id,
            "urls": worker_urls,
            "status": "pending",
            "created_at": time.time()
        })
        
        print(f"Worker {worker_id}: {len(worker_urls)} images")

if __name__ == "__main__":
    # Nettoyer la collection avant les tests
    db.download_tasks.delete_many({})
    
    # Tester différents scénarios
    test_batch_download(45)  # 45 images -> 3 workers (15 chacun)
    test_batch_download(20)  # 20 images -> 1 worker
    test_batch_download(35)  # 35 images -> 2 workers (18 et 17)
    test_batch_download(62)  # 62 images -> 4 workers (16, 16, 15, 15)
