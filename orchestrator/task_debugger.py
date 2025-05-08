import pymongo
import time
import os
import logging
import docker
import subprocess
import sys

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('task_debugger')

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL', 'mongodb://database:27017/imagesdb')
client = pymongo.MongoClient(DB_URL)
db = client.get_database()

# Configuration Docker
try:
    docker_client = docker.from_env()
    docker_api_client = docker.APIClient()
except Exception as e:
    logger.error(f"Erreur lors de la connexion à Docker: {e}")
    docker_client = None
    docker_api_client = None

def analyze_pending_task(task_id):
    """Analyse une tâche pendante spécifique"""
    try:
        # Récupérer la tâche
        task = db.download_tasks.find_one({"_id": task_id})
        if not task:
            task = db.tagging_tasks.find_one({"_id": task_id})
            
        if not task:
            logger.error(f"Tâche {task_id} non trouvée")
            return
        
        task_type = "téléchargement" if "urls" in task else "tagging"
        worker_id = task.get("worker_id")
        
        logger.info(f"=== ANALYSE DE LA TÂCHE {task_id} ===")
        logger.info(f"Type: {task_type}")
        logger.info(f"Statut: {task.get('status')}")
        logger.info(f"Worker ID assigné: {worker_id}")
        logger.info(f"Créée le: {time.ctime(task.get('created_at', 0))}")
        
        # Vérifier si le worker existe et fonctionne
        service_type = "image_downloader" if task_type == "téléchargement" else "image_tagger"
        container_name = f"{service_type}_{worker_id}"
        
        logger.info(f"\n=== ANALYSE DU WORKER {worker_id} ===")
        container = find_container_for_worker(service_type, worker_id)
        
        if not container:
            logger.error(f"❌ Aucun conteneur trouvé pour le worker {worker_id} ({service_type})")
            logger.info("Cela explique pourquoi la tâche reste en attente - le worker n'existe pas!")
            return
        
        # Vérifier l'état du conteneur
        status = container.status
        logger.info(f"Statut du conteneur: {status}")
        
        if status != 'running':
            logger.error(f"❌ Le conteneur du worker {worker_id} n'est pas en cours d'exécution (statut: {status})")
            logger.info("Cela explique pourquoi la tâche reste en attente - le worker n'est pas actif!")
            
            # Voir les logs du conteneur pour comprendre pourquoi il n'est pas en cours d'exécution
            try:
                logs = container.logs().decode('utf-8')
                logger.info(f"\nDernières lignes des logs du conteneur:\n{logs[-1000:] if logs else 'Pas de logs'}")
            except Exception as e:
                logger.error(f"Impossible de récupérer les logs: {e}")
            
            return
        
        # Vérifier les logs du conteneur pour voir s'il traite la tâche
        try:
            logs = container.logs().decode('utf-8')
            logger.info(f"\n=== LOGS DU CONTENEUR ===")
            logger.info(f"{logs[-1000:] if logs else 'Pas de logs'}")
            
            # Rechercher des erreurs importantes dans les logs
            if "ERROR" in logs or "Error" in logs or "error" in logs:
                error_lines = [line for line in logs.split('\n') if "ERROR" in line or "Error" in line or "error" in line]
                logger.info(f"\n=== ERREURS DANS LES LOGS ===")
                for line in error_lines[-5:]:  # Afficher les 5 dernières erreurs
                    logger.info(line)
        except Exception as e:
            logger.error(f"Impossible de récupérer les logs: {e}")
        
        # Vérifier si la tâche est visible par le worker dans la base de données
        logger.info(f"\n=== VÉRIFICATION DE L'ACCÈS À LA BASE DE DONNÉES ===")
        
        # Vérifier la connexion réseau du conteneur
        if docker_api_client:
            try:
                # Exécuter une commande ping pour vérifier la connectivité réseau
                exec_id = docker_api_client.exec_create(container.id, ["ping", "-c", "3", "database"])
                ping_output = docker_api_client.exec_start(exec_id).decode('utf-8')
                logger.info(f"Résultat du ping vers la base de données:\n{ping_output}")
            except Exception as e:
                logger.error(f"Impossible de tester la connexion réseau: {e}")
        
        # Recommendations
        logger.info(f"\n=== RECOMMENDATIONS ===")
        if status != 'running':
            logger.info("1. Redémarrez le conteneur du worker")
            logger.info(f"   docker start {container_name}")
            logger.info("2. Vérifiez que le worker accède correctement à la base de données")
        else:
            logger.info("1. Vérifiez que le worker est correctement configuré avec le bon WORKER_ID")
            logger.info("2. Assurez-vous que le worker peut accéder à la base de données MongoDB")
            logger.info("3. Redistribuez les tâches pendantes")
            logger.info(f"4. Si nécessaire, examinez les logs complets du worker")
            logger.info(f"   docker logs {container_name}")
    
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse de la tâche: {e}")
        import traceback
        traceback.print_exc()

def find_container_for_worker(service_type, worker_id):
    """Trouve le conteneur correspondant à un worker spécifique"""
    if not docker_client:
        return None
    
    try:
        # Recherche par nom de conteneur exact
        container_name = f"{service_type}_{worker_id}"
        try:
            return docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            pass  # Continuer avec la recherche par filtre
        
        # Recherche par labels et variables d'environnement
        containers = docker_client.containers.list(
            all=True,
            filters={"label": [f"com.docker.compose.service={service_type}"]}
        )
        
        for container in containers:
            env_vars = container.attrs.get('Config', {}).get('Env', [])
            for env in env_vars:
                if env == f"WORKER_ID={worker_id}":
                    return container
        
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la recherche du conteneur: {e}")
        return None

def analyze_all_pending_tasks():
    """Analyse toutes les tâches pendantes"""
    # Récupérer toutes les tâches pendantes
    pending_downloads = list(db.download_tasks.find({"status": "pending"}))
    pending_tagging = list(db.tagging_tasks.find({"status": "pending"}))
    
    logger.info(f"=== RÉSUMÉ ===")
    logger.info(f"Tâches de téléchargement pendantes: {len(pending_downloads)}")
    logger.info(f"Tâches de tagging pendantes: {len(pending_tagging)}")
    
    # Analyser chaque tâche
    for task in pending_downloads:
        analyze_pending_task(task["_id"])
    
    for task in pending_tagging:
        analyze_pending_task(task["_id"])

def list_all_containers():
    """Liste tous les conteneurs liés au projet"""
    if not docker_client:
        return
    
    try:
        logger.info(f"\n=== TOUS LES CONTENEURS ===")
        containers = docker_client.containers.list(all=True)
        
        for container in containers:
            if "partie2" in container.name or "image_" in container.name:
                logger.info(f"Nom: {container.name}")
                logger.info(f"  ID: {container.id[:12]}")
                logger.info(f"  Statut: {container.status}")
                
                # Afficher les variables d'environnement liées au worker_id
                env_vars = container.attrs.get('Config', {}).get('Env', [])
                worker_id = None
                for env in env_vars:
                    if "WORKER_ID" in env:
                        worker_id = env
                logger.info(f"  {worker_id if worker_id else 'Pas de WORKER_ID'}")
                
                # Vérifier si le conteneur est en réseau avec la base de données
                networks = container.attrs.get('NetworkSettings', {}).get('Networks', {})
                logger.info(f"  Réseaux: {', '.join(networks.keys())}")
                
                logger.info("")
    except Exception as e:
        logger.error(f"Erreur lors de la liste des conteneurs: {e}")

if __name__ == "__main__":
    logger.info("=== OUTIL DE DIAGNOSTIC DES TÂCHES PENDANTES ===")
    
    # Lister tous les conteneurs
    list_all_containers()
    
    # Si un ID de tâche est fourni en argument, analyser uniquement cette tâche
    if len(sys.argv) > 1:
        task_id = sys.argv[1]
        analyze_pending_task(task_id)
    else:
        # Sinon, analyser toutes les tâches pendantes
        analyze_all_pending_tasks()
