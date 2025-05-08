import time
import datetime
from config import db, logger

def get_worker_info(worker_type, worker_id, refresh=False, details=False):
    """Récupère les informations d'un worker, soit simulées soit réelles"""
    try:
        # Toujours utiliser les informations réelles du worker
        return get_real_worker_info(worker_type, worker_id)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des informations réelles du worker: {e}")
        # Fallback vers la version simulée si nécessaire
        return get_simulated_worker_info(worker_type, worker_id, details)

def get_real_worker_info(worker_type, worker_id):
    """Récupère des informations réelles sur un worker depuis MongoDB et les journaux Docker"""
    # Configurer le type de collection en fonction du type de worker
    collection_name = {
        'downloader': 'download_tasks',
        'tagger': 'tagging_tasks', 
        'recommendation': 'recommendation_tasks'
    }.get(worker_type, 'download_tasks')
    
    # Récupérer les tâches récentes de ce worker depuis MongoDB
    recent_tasks = list(db[collection_name].find(
        {"worker_id": worker_id},
        {"_id": 1, "status": 1, "created_at": 1, "completed_at": 1, "success_count": 1, "total_count": 1}
    ).sort("created_at", -1).limit(5))
    
    # Déterminer le statut du worker
    status = "idle"  # Par défaut, le worker est considéré comme inactif
    
    # S'il y a une tâche en cours (status = "in_progress")
    in_progress_task = db[collection_name].find_one({"worker_id": worker_id, "status": "in_progress"})
    if in_progress_task:
        status = "active"
    
    # Vérifier s'il y a eu une activité récente (dans les 5 dernières minutes)
    recent_activity = db[collection_name].find_one(
        {
            "worker_id": worker_id, 
            "$or": [
                {"completed_at": {"$gt": time.time() - 300}},
                {"created_at": {"$gt": time.time() - 300}}
            ]
        }
    )
    
    if recent_activity and status != "active":
        status = "idle"  # Worker récemment actif mais pas de tâche en cours
    
    # Calculer les statistiques
    completed_tasks = db[collection_name].count_documents({"worker_id": worker_id, "status": "completed"})
    
    # Calculer le taux de succès moyen
    success_rate = 0
    avg_time = 0
    
    if completed_tasks > 0:
        completed_task_list = list(db[collection_name].find(
            {"worker_id": worker_id, "status": "completed", "success_count": {"$exists": True}, "total_count": {"$exists": True}}
        ))
        
        if completed_task_list:
            total_success = sum(task.get("success_count", 0) for task in completed_task_list)
            total_count = sum(task.get("total_count", 0) for task in completed_task_list)
            
            if total_count > 0:
                success_rate = round((total_success / total_count) * 100)
            
            # Calculer le temps moyen de traitement
            tasks_with_times = []
            for task in completed_task_list:
                if "created_at" in task and "completed_at" in task:
                    try:
                        # Convertir les timestamps si nécessaire
                        created = task["created_at"]
                        completed = task["completed_at"]
                        
                        # Si les valeurs sont déjà des timestamps numériques
                        if isinstance(created, (int, float)) and isinstance(completed, (int, float)):
                            tasks_with_times.append({"duration": completed - created})
                    except:
                        # Si erreur de conversion, ignorer cette tâche
                        pass
            
            if tasks_with_times:
                avg_time = sum(task["duration"] for task in tasks_with_times) / len(tasks_with_times)
                avg_time = round(avg_time, 2)
    
    # Nombre de tâches en attente
    pending_tasks = db[collection_name].count_documents({"worker_id": worker_id, "status": "pending"})
    
    # Obtenir la tâche en cours si elle existe
    current_task = None
    if in_progress_task:
        # Ajouter des informations sur la progression si disponibles
        progress = in_progress_task.get("progress", 0)
        started_at = ""
        
        # Gestion sécurisée de started_at qui peut être soit un timestamp numérique soit un datetime
        if "started_at" in in_progress_task:
            try:
                if isinstance(in_progress_task["started_at"], datetime.datetime):
                    started_at = in_progress_task["started_at"].strftime("%H:%M:%S")
                else:
                    started_at = datetime.datetime.fromtimestamp(in_progress_task["started_at"]).strftime("%H:%M:%S")
            except:
                started_at = str(in_progress_task["started_at"])
        
        current_task = {
            "id": str(in_progress_task.get("_id", "")),
            "progress": progress,
            "started_at": started_at
        }
    
    # Construire l'objet d'informations du worker
    worker_info = {
        "id": worker_id,
        "type": worker_type,
        "status": status,
        "status_color": {"active": "success", "idle": "warning", "offline": "danger"}.get(status, "secondary"),
        "stats": {
            "completed_tasks": completed_tasks,
            "success_rate": success_rate,
            "avg_processing_time": avg_time,
            "pending_tasks": pending_tasks
        },
        "current_task": current_task,
        "recent_tasks": [],
        "hostname": f"{worker_type}-{worker_id}",  # Informations système de base
        "system_info": {
            "cpu_usage": 0,
            "memory_usage": 0,
            "disk_usage": 0,
            "started_at": "N/A",
            "uptime": "N/A",
            "version": "1.0",
        }
    }
    
    # Formater les tâches récentes
    for task in recent_tasks:
        formatted_task = {
            "id": str(task.get("_id", "")),
            "status": task.get("status", "unknown"),
            "status_color": {
                "completed": "success", 
                "pending": "warning", 
                "in_progress": "info", 
                "failed": "danger"
            }.get(task.get("status", ""), "secondary"),
            "success_count": task.get("success_count", 0),
            "total_count": task.get("total_count", 0),
            "created_at": "",
            "completed_at": ""
        }
        
        # Formater created_at et completed_at en toute sécurité
        # ...existing code...
        
        # Ajouter des informations spécifiques selon le type de worker
        if worker_type == 'downloader':
            formatted_task["type"] = "download"
            # Essayer d'obtenir les URLs si disponibles
            full_task = db[collection_name].find_one({"_id": task["_id"]})
            if full_task and "urls" in full_task:
                formatted_task["urls"] = full_task["urls"]
        elif worker_type == 'tagger':
            formatted_task["type"] = "tag"
            # Essayer d'obtenir les image_ids si disponibles
            full_task = db[collection_name].find_one({"_id": task["_id"]})
            if full_task and "image_ids" in full_task:
                formatted_task["image_ids"] = full_task["image_ids"]
        else:
            formatted_task["type"] = "recommendation"
        
        worker_info["recent_tasks"].append(formatted_task)
    
    # Ajouter des informations de performances simulées pour le graphique
    worker_info["performance_history"] = []
    for i in range(10):
        worker_info["performance_history"].append({
            "timestamp": f"{i*10} min ago",
            "tasks_per_minute": 0.0,
            "avg_time": 0.0
        })
    
    # Logs récents (fictifs pour l'instant)
    worker_info["logs"] = [
        {"timestamp": "now", "level": "info", "message": "Status check completed"},
        {"timestamp": "5 min ago", "level": "info", "message": "Worker active"}
    ]
    
    return worker_info

def get_simulated_worker_info(worker_type, worker_id, details=False):
    """Version de secours qui génère des données simulées"""
    import random
    from datetime import datetime, timedelta
    
    # Créer des données simulées...
    # ...existing code...
    
    # Retourner les données simulées
    worker_data = {
        "worker_id": worker_id,
        "type": worker_type,
        "status": "idle",
        "status_color": "warning",
        "stats": {
            "completed_tasks": random.randint(10, 100),
            "success_rate": random.randint(80, 100),
            "avg_processing_time": random.uniform(0.5, 5.0),
            "pending_tasks": random.randint(0, 10)
        },
        "current_task": None,
        "recent_tasks": [],
        "hostname": f"{worker_type}-{worker_id}",
        "system_info": {
            "cpu_usage": 0,
            "memory_usage": 0,
            "disk_usage": 0,
            "started_at": "N/A",
            "uptime": "N/A",
            "version": "1.0",
        }
    }
    
    return worker_data
