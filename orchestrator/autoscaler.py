import os
import time
import logging
import docker
from pymongo import MongoClient
import traceback
import json
import subprocess

# Configuration du logger avec plus de détails
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levellevel)s - %(message)s',
                   handlers=[
                       logging.StreamHandler(),  # Pour afficher dans la console
                   ])
logger = logging.getLogger('autoscaler')

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL', 'mongodb://database:27017/imagesdb')
client = MongoClient(DB_URL)
db = client.get_database()

# Constantes pour l'autoscaling
IMAGES_PER_WORKER = 20  # Maximum d'images par worker
MAX_WORKERS = 5  # Nombre maximum de workers par type
DEPLOYMENT_TIMEOUT = 60  # Timeout en secondes pour le déploiement d'un conteneur
PROJECT_NAME = "partie2"  # Nom du projet docker-compose

# Initialisation du client Docker avec gestion des erreurs explicite
try:
    docker_client = docker.from_env()
    # Test de la connexion
    docker_client.ping()
    logger.info("✅ Connexion au démon Docker établie avec succès")
except Exception as e:
    logger.error(f"❌ ERREUR lors de la connexion au démon Docker: {e}")
    traceback.print_exc()
    docker_client = None

def get_active_worker_ids(service_name):
    """Récupère les IDs de worker actuellement actifs pour un service"""
    worker_ids = []
    
    try:
        if not docker_client:
            return worker_ids
        
        containers = docker_client.containers.list(
            all=True,
            filters={
                "label": [f"com.docker.compose.service={service_name}"]
            }
        )
        
        for container in containers:
            # Récupérer le worker_id des variables d'environnement
            env_vars = container.attrs.get('Config', {}).get('Env', [])
            for env in env_vars:
                if env.startswith('WORKER_ID='):
                    worker_id = int(env.split('=')[1])
                    if container.status == 'running':
                        worker_ids.append(worker_id)
                    break
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des IDs de worker actifs: {e}")
    
    return worker_ids

def get_next_worker_id(service_name):
    """Détermine le prochain worker_id disponible"""
    active_ids = get_active_worker_ids(service_name)
    
    if not active_ids:
        return 1  # Si aucun worker actif, commencer à 1
    
    # Trouver le premier ID disponible
    next_id = 1
    while next_id in active_ids and next_id <= MAX_WORKERS:
        next_id += 1
    
    return next_id

def create_new_worker_container(service_name, worker_id):
    """Crée un nouveau conteneur avec un worker_id spécifique"""
    try:
        logger.info(f"🚀 Création d'un nouveau conteneur {service_name} avec worker_id={worker_id}")
        
        # Nom du service et du conteneur
        container_name = f"{service_name}_{worker_id}"
        
        # Vérifie si un conteneur avec ce nom existe déjà et le supprime
        try:
            existing = docker_client.containers.get(container_name)
            logger.warning(f"⚠️ Un conteneur {container_name existe déjà, statut: {existing.status}")
            
            if existing.status != 'running':
                logger.warning(f"⚠️ Suppression du conteneur existant {container_name}")
                existing.remove(force=True)
                logger.info(f"✅ Conteneur {container_name} supprimé")
        except docker.errors.NotFound:
            pass  # Le conteneur n'existe pas, c'est ce qu'on veut
        except Exception as e:
            logger.error(f"❌ Erreur lors de la vérification/suppression du conteneur existant: {e}")
        
        # Créer le nouveau conteneur avec le bon worker_id
        image_name = f"{COMPOSE_PROJECT}_{service_name}"
        logger.info(f"🔄 Utilisation de l'image {image_name}")
        
        new_container = docker_client.containers.run(
            image_name,
            name=container_name,
            detach=True,
            environment={
                "WORKER_ID": str(worker_id),
                "DATABASE_URL": DB_URL
            },
            volumes={
                f"{COMPOSE_PROJECT}_shared_data": {"bind": "/data", "mode": "rw"}
            },
            network=f"{COMPOSE_PROJECT}_app_network",
            labels={
                "com.docker.compose.project": COMPOSE_PROJECT,
                "com.docker.compose.service": service_name
            }
        )
        
        logger.info(f"✅ Conteneur {container_name} créé avec succès, ID: {new_container.id[:12]}")
        
        # Vérifier le statut du nouveau conteneur
        status = new_container.status
        logger.info(f"📊 Statut initial du conteneur {container_name}: {status}")
        
        # Attendre que le conteneur soit prêt
        start_time = time.time()
        while time.time() - start_time < DEPLOYMENT_TIMEOUT:
            new_container.reload()
            status = new_container.status
            logger.info(f"⏳ Attente du démarrage du conteneur {container_name}, statut: {status}")
            
            if status == 'running':
                logger.info(f"✅ Conteneur {container_name} démarré avec succès")
                # Vérifier les logs du conteneur pour s'assurer qu'il fonctionne
                logs = new_container.logs().decode('utf-8')
                logger.info(f"📜 Derniers logs du conteneur {container_name}: {logs[-200:] if logs else 'Pas de logs'}")
                return True
            
            time.sleep(2)
        
        logger.error(f"❌ Timeout: Le conteneur {container_name} n'est pas passé à l'état 'running'")
        return False
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création du conteneur {service_name}_{worker_id}: {e}")
        traceback.print_exc()
        return False

def scale_service_compose(service_name, count):
    """Utilise docker-compose pour mettre à l'échelle un service"""
    try:
        # S'assurer que le nombre est dans les limites
        count = max(1, min(count, MAX_WORKERS))
        
        logger.info(f"🔄 Tentative de mise à l'échelle de {service_name} à {count} instances via docker-compose")
        
        # Exécuter la commande docker-compose scale
        cmd = f"docker-compose -p {COMPOSE_PROJECT} -f {COMPOSE_FILE} up -d --scale {service_name}={count} {service_name}"
        logger.info(f"📝 Commande: {cmd}")
        
        process = subprocess.run(
            cmd,
            shell=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        if process.returncode == 0:
            logger.info(f"✅ Scaling réussi pour {service_name}: {count} instances")
            stdout = process.stdout.decode('utf-8')
            logger.info(f"📝 Sortie standard: {stdout}")
            return True
        else:
            stderr = process.stderr.decode('utf-8')
            logger.error(f"❌ Échec du scaling pour {service_name}: {stderr}")
            
            # Le scaling via docker-compose a échoué, tentons une approche manuelle
            logger.info(f"🔄 Tentative de scaling manuel pour {service_name}")
            return scale_service_manually(service_name, count)
    
    except Exception as e:
        logger.error(f"❌ Erreur lors du scaling via docker-compose: {e}")
        traceback.print_exc()
        
        # Fallback sur la méthode manuelle
        return scale_service_manually(service_name, count)

def scale_service_manually(service_name, target_count):
    """Tente de scaler manuellement un service en créant/supprimant des conteneurs"""
    try:
        # Obtenir les worker IDs actuels
        active_worker_ids = get_active_worker_ids(service_name)
        current_count = len(active_worker_ids)
        
        logger.info(f"📊 État actuel de {service_name}: {current_count} workers actifs avec IDs {active_worker_ids}")
        
        # Si nous avons besoin de plus de workers
        if target_count > current_count:
            success_count = 0
            for _ in range(target_count - current_count):
                next_id = get_next_worker_id(service_name)
                if next_id <= MAX_WORKERS:
                    if create_new_worker_container(service_name, next_id):
                        success_count += 1
                else:
                    logger.warning(f"⚠️ Impossible de créer plus de workers, limite atteinte: {MAX_WORKERS}")
                    break
            
            logger.info(f"📊 Scaling manuel terminé: {success_count}/{target_count - current_count} nouvelles instances créées")
            return success_count > 0
        
        # Si nous avons besoin de moins de workers (ne pas implémenter pour l'instant)
        elif target_count < current_count:
            logger.info(f"⚠️ Réduction du nombre de workers non implémentée pour le moment")
            return False
        
        # Déjà au bon nombre
        else:
            logger.info(f"✅ Déjà au bon nombre de workers ({current_count})")
            return True
    
    except Exception as e:
        logger.error(f"❌ Erreur lors du scaling manuel: {e}")
        traceback.print_exc()
        return False

def check_and_scale():
    """Vérifie la charge actuelle et scale les services si nécessaire"""
    try:
        # Récupérer les informations de tous les conteneurs pour le monitoring
        all_containers = []
        if docker_client:
            containers = docker_client.containers.list(all=True)
            for container in containers:
                all_containers.append({
                    "id": container.id[:12],
                    "name": container.name,
                    "status": container.status,
                    "labels": container.labels
                })
        
        # Enregistrer l'état actuel pour le monitoring
        db.container_status.delete_many({})
        for container in all_containers:
            db.container_status.insert_one(container)
        
        # === DOWNLOADER SCALING ===
        # Compter les URLs en attente de téléchargement
        pending_download_urls = 0
        download_tasks = list(db.download_tasks.find({"status": "pending"}))
        
        for task in download_tasks:
            urls = task.get("urls", [])
            if isinstance(urls, list):
                pending_download_urls += len(urls)
        
        # Calculer le nombre de workers nécessaires
        required_downloaders = max(1, min(MAX_WORKERS, (pending_download_urls + IMAGES_PER_WORKER - 1) // IMAGES_PER_WORKER))
        logger.info(f"📈 URLs en attente: {pending_download_urls}, téléchargeurs nécessaires: {required_downloaders}")
        
        # Vérifier l'état actuel des downloaders
        active_downloader_ids = get_active_worker_ids("image_downloader")
        current_downloaders = len(active_downloader_ids)
        
        # Ajuster le nombre de downloaders si nécessaire et s'il y a des tâches en attente
        if pending_download_urls > 0 and required_downloaders > current_downloaders:
            logger.info(f"🔄 Besoin de {required_downloaders} téléchargeurs, actuellement {current_downloaders}")
            
            # Essayer d'abord l'approche docker-compose
            success = scale_service_compose("image_downloader", required_downloaders)
            
            if not success:
                # Fallback: créer manuellement les conteneurs supplémentaires
                for i in range(current_downloaders + 1, required_downloaders + 1):
                    worker_id = get_next_worker_id("image_downloader")
                    create_new_worker_container("image_downloader", worker_id)
        
        # === TAGGER SCALING ===
        # Compter les images non taguées
        pending_tag_images = db.images.count_documents({"tagged": {"$ne": True}})
        
        # Calculer le nombre de taggers nécessaires
        required_taggers = max(1, min(MAX_WORKERS, (pending_tag_images + IMAGES_PER_WORKER - 1) // IMAGES_PER_WORKER))
        logger.info(f"📈 Images à tagger: {pending_tag_images, taggers nécessaires: {required_taggers}")
        
        # Vérifier l'état actuel des taggers
        active_tagger_ids = get_active_worker_ids("image_tagger")
        current_taggers = len(active_tagger_ids)
        
        # Ajuster le nombre de taggers si nécessaire et s'il y a des images à tagger
        if pending_tag_images > 0 and required_taggers > current_taggers:
            logger.info(f"🔄 Besoin de {required_taggers} taggers, actuellement {current_taggers}")
            
            # Essayer d'abord l'approche docker-compose
            success = scale_service_compose("image_tagger", required_taggers)
            
            if not success:
                # Fallback: créer manuellement les conteneurs supplémentaires
                for i in range(current_taggers + 1, required_taggers + 1):
                    worker_id = get_next_worker_id("image_tagger")
                    create_new_worker_container("image_tagger", worker_id)
        
        # Assurer que les tâches sont bien réparties entre les workers
        redistribute_pending_tasks()
        
        # Enregistrer les statistiques pour le dashboard
        db.autoscaler_stats.insert_one({
            "timestamp": time.time(),
            "pending_download_urls": pending_download_urls,
            "required_downloaders": required_downloaders,
            "current_downloaders": current_downloaders,
            "pending_tag_images": pending_tag_images,
            "required_taggers": required_taggers,
            "current_taggers": current_taggers,
            "container_count": len(all_containers)
        })
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Erreur dans la fonction check_and_scale: {e}")
        traceback.print_exc()
        return False

def redistribute_pending_tasks():
    """Redistribue les tâches en attente aux workers actifs"""
    try:
        # Récupérer les IDs des workers actifs
        downloader_ids = get_active_worker_ids("image_downloader")
        tagger_ids = get_active_worker_ids("image_tagger")
        
        # Si aucun worker n'est actif, inutile de continuer
        if not downloader_ids and not tagger_ids:
            logger.warning("⚠️ Aucun worker actif, impossible de redistribuer les tâches")
            return False
        
        # Redistribuer les tâches de téléchargement
        if downloader_ids:
            pending_download_tasks = list(db.download_tasks.find({"status": "pending"}))
            
            for i, task in enumerate(pending_download_tasks):
                # Assigner la tâche à un worker actif de manière cyclique
                worker_id = downloader_ids[i % len(downloader_ids)]
                
                # Mettre à jour la tâche uniquement si nécessaire
                current_worker_id = task.get("worker_id")
                if current_worker_id != worker_id or current_worker_id not in downloader_ids:
                    db.download_tasks.update_one(
                        {"_id": task["_id"]},
                        {"$set": {"worker_id": worker_id}}
                    )
                    logger.info(f"♻️ Tâche de téléchargement {task['_id']} réattribuée au worker {worker_id}")
        
        # Redistribuer les tâches de tagging
        if tagger_ids:
            pending_tagging_tasks = list(db.tagging_tasks.find({"status": "pending"}))
            
            for i, task in enumerate(pending_tagging_tasks):
                # Assigner la tâche à un worker actif de manière cyclique
                worker_id = tagger_ids[i % len(tagger_ids)]
                
                # Mettre à jour la tâche uniquement si nécessaire
                current_worker_id = task.get("worker_id")
                if current_worker_id != worker_id or current_worker_id not in tagger_ids:
                    db.tagging_tasks.update_one(
                        {"_id": task["_id"]},
                        {"$set": {"worker_id": worker_id}}
                    )
                    logger.info(f"♻️ Tâche de tagging {task['_id']} réattribuée au worker {worker_id}")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la redistribution des tâches: {e}")
        traceback.print_exc()
        return False

def run_autoscaler():
    """Fonction principale qui vérifie périodiquement la charge et ajuste les workers"""
    logger.info("🚀 Démarrage de l'autoscaler")
    
    while True:
        try:
            check_and_scale()
            time.sleep(10)  # Vérifier toutes les 10 secondes
        except Exception as e:
            logger.error(f"❌ Erreur dans la boucle autoscaler: {e}")
            traceback.print_exc()
            time.sleep(30)  # Attendre plus longtemps en cas d'erreur

if __name__ == "__main__":
    run_autoscaler()
