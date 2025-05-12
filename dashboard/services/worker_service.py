import datetime
import time
from app import db

def get_real_worker_info(worker_type, worker_id):
    """Récupère des informations réelles sur un worker depuis MongoDB"""
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
    
    # ...existing code... (Calcul des statistiques détaillées)
    
    # Construire l'objet d'informations du worker
    worker_info = {
        "id": worker_id,
        "type": worker_type,
        "status": status,
        "status_color": {"active": "success", "idle": "warning", "offline": "danger"}.get(status, "secondary"),
        "stats": get_worker_stats(collection_name, worker_id, completed_tasks),
        "current_task": format_current_task(in_progress_task) if in_progress_task else None,
        "recent_tasks": format_recent_tasks(recent_tasks, worker_type, collection_name),
        "hostname": f"{worker_type}-{worker_id}",
        "system_info": get_system_info(),
        "performance_history": get_performance_history(),
        "logs": get_worker_logs()
    }
    
    return worker_info

def get_worker_stats(collection_name, worker_id, completed_tasks):
    """Obtient les statistiques d'un worker"""
    # ...existing code...
    success_rate = 0
    avg_time = 0
    pending_tasks = db[collection_name].count_documents({"worker_id": worker_id, "status": "pending"})
    
    # Calcul du taux de succès et du temps moyen (code similaire à l'original)
    
    return {
        "completed_tasks": completed_tasks,
        "success_rate": success_rate,
        "avg_processing_time": avg_time,
        "pending_tasks": pending_tasks
    }

def format_current_task(task):
    """Formate une tâche en cours pour l'affichage"""
    # ...existing code...
    return {
        "id": str(task.get("_id", "")),
        "progress": task.get("progress", 0),
        "started_at": format_timestamp(task.get("started_at", ""))
    }

def format_recent_tasks(tasks, worker_type, collection_name):
    """Formate les tâches récentes pour l'affichage"""
    # ...existing code...
    formatted_tasks = []
    
    for task in tasks:
        formatted_task = {
            "id": str(task.get("_id", "")),
            "status": task.get("status", "unknown"),
            "status_color": get_status_color(task.get("status", "")),
            "success_count": task.get("success_count", 0),
            "total_count": task.get("total_count", 0),
            "created_at": format_timestamp(task.get("created_at", "")),
            "completed_at": format_timestamp(task.get("completed_at", ""))
        }
        
        # Ajout des infos spécifiques selon le type de worker
        if worker_type == 'downloader':
            formatted_task["type"] = "download"
            add_urls_info(formatted_task, task, collection_name)
        elif worker_type == 'tagger':
            formatted_task["type"] = "tag"
            add_images_info(formatted_task, task, collection_name)
        else:
            formatted_task["type"] = "recommendation"
        
        formatted_tasks.append(formatted_task)
    
    return formatted_tasks

def get_status_color(status):
    """Retourne la couleur CSS associée à un statut"""
    return {
        "completed": "success", 
        "pending": "warning", 
        "in_progress": "info", 
        "failed": "danger"
    }.get(status, "secondary")

def add_urls_info(task_data, task, collection_name):
    """Ajoute les infos d'URLs à une tâche de téléchargement"""
    # ...existing code...
    full_task = db[collection_name].find_one({"_id": task["_id"]})
    if full_task and "urls" in full_task:
        task_data["urls"] = full_task["urls"]
    return task_data

def add_images_info(task_data, task, collection_name):
    """Ajoute les infos d'IDs d'image à une tâche de tagging"""
    # ...existing code...
    full_task = db[collection_name].find_one({"_id": task["_id"]})
    if full_task and "image_ids" in full_task:
        task_data["image_ids"] = full_task["image_ids"]
    return task_data

def format_timestamp(timestamp):
    """Formate un timestamp en date lisible"""
    try:
        if isinstance(timestamp, datetime.datetime):
            return timestamp.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(timestamp, (int, float)):
            return datetime.datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            return str(timestamp)
    except:
        return str(timestamp)

def get_system_info():
    """Retourne les informations système simulées d'un worker"""
    return {
        "cpu_usage": 30,
        "memory_usage": 40,
        "disk_usage": 20,
        "started_at": "N/A",
        "uptime": "N/A",
        "version": "1.0",
    }

def get_performance_history():
    """Retourne l'historique de performance simulé d'un worker"""
    return [
        {"timestamp": f"{i*10} min ago", "tasks_per_minute": 0.0, "avg_time": 0.0}
        for i in range(10)
    ]

def get_worker_logs():
    """Retourne des logs simulés d'un worker"""
    return [
        {"timestamp": "now", "level": "info", "message": "Status check completed"},
        {"timestamp": "5 min ago", "level": "info", "message": "Worker active"}
    ]