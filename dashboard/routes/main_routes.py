from flask import Blueprint, render_template, redirect, url_for
from config import db
import datetime

main_routes = Blueprint('main', __name__)

@main_routes.route('/')
def index():
    """Page d'accueil du dashboard"""
    # Statistiques générales
    stats = {
        'images_count': db.images.count_documents({}),
        'tagged_images': db.images.count_documents({"tagged": True}),
        'users_count': db.users.count_documents({}),
        'recommendations_count': db.recommendations.count_documents({})
    }
    
    # État des workers avec informations enrichies
    downloader_tasks = enrich_tasks(
        list(db.download_tasks.find().sort('created_at', -1).limit(10)), 
        "downloader"
    )
    
    tagger_tasks = enrich_tasks(
        list(db.tagging_tasks.find().sort('created_at', -1).limit(5)), 
        "tagger"
    )
    
    recommendation_tasks = enrich_tasks(
        list(db.recommendation_tasks.find().sort('created_at', -1).limit(5)), 
        "recommendation"
    )
    
    # Regrouper les tâches par worker
    downloaders = group_tasks_by_worker(downloader_tasks)
    
    return render_template('index.html', 
                          stats=stats,
                          downloader_tasks=downloader_tasks,
                          tagger_tasks=tagger_tasks,
                          recommendation_tasks=recommendation_tasks,
                          downloaders=downloaders)

def enrich_tasks(tasks, task_type):
    """Enrichit les données des tâches avec des informations supplémentaires"""
    for task in tasks:
        # Ajouter le nom du worker
        worker_id = task.get('worker_id', '?')
        task['worker_name'] = f"Worker {worker_id}"
        
        # Calculer la progression
        if task.get('status') == 'completed':
            task['progress_text'] = "Terminé"
            task['progress_percent'] = 100
        elif task.get('status') == 'in_progress':
            success = task.get('success_count', 0)
            total = task.get('total_count', 0)
            if total > 0:
                task['progress_text'] = f"{success}/{total}"
                task['progress_percent'] = int((success / total) * 100)
            else:
                task['progress_text'] = "En cours"
                task['progress_percent'] = 50
        elif task.get('status') == 'pending':
            task['progress_text'] = "En attente"
            task['progress_percent'] = 0
        else:
            task['progress_text'] = task.get('status', "Inconnu")
            task['progress_percent'] = 0
            
        # Ajouter classe CSS pour la coloration
        statuses = {
            'pending': 'text-warning', 
            'in_progress': 'text-info',
            'completed': 'text-success', 
            'failed': 'text-danger'
        }
        task['status_class'] = statuses.get(task.get('status'), 'text-secondary')
        
        # Formater la date
        if 'created_at' in task:
            if isinstance(task['created_at'], (int, float)):
                task['created_at_fmt'] = datetime.datetime.fromtimestamp(
                    task['created_at']).strftime('%H:%M:%S, %d/%m/%Y')
            else:
                try:
                    task['created_at_fmt'] = task['created_at'].strftime('%H:%M:%S, %d/%m/%Y')
                except:
                    task['created_at_fmt'] = str(task['created_at'])
    
    return tasks

def group_tasks_by_worker(tasks):
    """Regroupe les tâches par worker pour une meilleure visualisation"""
    workers = {}
    for task in tasks:
        worker_id = task.get('worker_id', '?')
        if worker_id not in workers:
            workers[worker_id] = {
                'name': f"Worker {worker_id}",
                'tasks': [],
                'status': 'idle'
            }
        
        workers[worker_id]['tasks'].append(task)
        
        # Mettre à jour le statut du worker
        if task.get('status') == 'in_progress':
            workers[worker_id]['status'] = 'active'
        elif workers[worker_id]['status'] == 'idle' and task.get('status') == 'pending':
            workers[worker_id]['status'] = 'pending'
    
    return workers
