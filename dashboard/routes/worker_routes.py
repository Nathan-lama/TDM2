from flask import Blueprint, render_template, request, redirect, url_for, flash
from config import db, orchestrator_client
import traceback
from services.worker_service import get_real_worker_info

worker_routes = Blueprint('worker', __name__, url_prefix='/workers')

@worker_routes.route('/')
def workers_list():
    """Affiche la liste des workers et leur état"""
    try:
        # Récupérer les données réelles des workers depuis MongoDB
        downloader_workers = []
        for worker_id in range(1, 3):
            worker_info = get_real_worker_info('downloader', worker_id)
            downloader_workers.append(worker_info)
        
        tagger_workers = []
        for worker_id in range(1, 3):
            worker_info = get_real_worker_info('tagger', worker_id)
            tagger_workers.append(worker_info)
        
        recommendation_worker = get_real_worker_info('recommendation', 1)
        
        # Statistiques globales
        all_workers = downloader_workers + tagger_workers + [recommendation_worker]
        total_workers = len(all_workers)
        active_workers = sum(1 for w in all_workers if w['status'] == 'active')
        idle_workers = sum(1 for w in all_workers if w['status'] == 'idle')
        offline_workers = sum(1 for w in all_workers if w['status'] == 'offline')
        
        return render_template('workers.html', 
                            downloader_workers=downloader_workers,
                            tagger_workers=tagger_workers,
                            recommendation_worker=recommendation_worker,
                            total_workers=total_workers,
                            active_workers=active_workers,
                            idle_workers=idle_workers,
                            offline_workers=offline_workers)
                            
    except Exception as e:
        traceback.print_exc()
        flash(f"Erreur lors du chargement des informations des workers: {str(e)}", "danger")
        return redirect(url_for('main.index'))

@worker_routes.route('/detail/<worker_type>/<int:worker_id>')
def worker_detail(worker_type, worker_id):
    """Affiche les détails d'un worker spécifique"""
    try:
        worker = get_real_worker_info(worker_type, worker_id)
        return render_template('worker_details.html', worker=worker)
    except Exception as e:
        traceback.print_exc()
        flash(f"Erreur lors du chargement des détails du worker: {str(e)}", "danger")
        return redirect(url_for('worker.workers_list'))

@worker_routes.route('/debug')
def worker_debug():
    """Page de debugging pour voir l'état des workers et des conteneurs Docker"""
    try:
        # Récupérer les données des conteneurs depuis MongoDB
        containers = list(db.container_status.find())
        
        # Récupérer les tâches en attente
        pending_download_tasks = list(db.download_tasks.find({"status": "pending"}))
        pending_tagging_tasks = list(db.tagging_tasks.find({"status": "pending"}))
        
        # Grouper les conteneurs par service
        services = {}
        for container in containers:
            service = container.get("service", "unknown")
            if service not in services:
                services[service] = []
            services[service].append(container)
        
        # Récupérer les statistiques de l'autoscaler
        autoscaler_stats = list(db.autoscaler_stats.find().sort("timestamp", -1).limit(20))
        
        # Récupérer les événements de scaling
        scaling_events = list(db.scaling_events.find().sort("timestamp", -1).limit(20))
        
        return render_template('worker_debug.html',
                              containers=containers,
                              services=services,
                              pending_download_tasks=pending_download_tasks,
                              pending_tagging_tasks=pending_tagging_tasks,
                              autoscaler_stats=autoscaler_stats,
                              scaling_events=scaling_events)
    except Exception as e:
        flash(f"Erreur lors de la récupération des informations de debugging: {str(e)}", "danger")
        return redirect(url_for('main.index'))

@worker_routes.route('/restart/<service_name>/<int:worker_id>', methods=['POST'])
def restart_container(service_name, worker_id):
    """Redémarre le conteneur associé à un worker via l'orchestrateur"""
    success, message = orchestrator_client.restart_container(service_name, worker_id)
    
    if success:
        flash(message, "success")
    else:
        flash(f"Erreur: {message}", "danger")
    
    # Rediriger vers la page appropriée
    referer = request.referrer
    if referer and 'task_debug' in referer:
        task_id = referer.split('/')[-1]
        return redirect(url_for('task.task_debug', task_id=task_id))
    else:
        return redirect(url_for('worker.worker_debug'))

@worker_routes.route('/create/<service_name>/<int:worker_id>', methods=['POST'])
def create_container(service_name, worker_id):
    """Crée un nouveau conteneur pour un worker via l'orchestrateur"""
    success, message = orchestrator_client.create_container(service_name, worker_id)
    
    if success:
        flash(message, "success")
    else:
        flash(f"Erreur: {message}", "danger")
    
    # Rediriger vers la page appropriée
    referer = request.referrer
    if referer and 'task_debug' in referer:
        task_id = referer.split('/')[-1]
        return redirect(url_for('task.task_debug', task_id=task_id))
    else:
        return redirect(url_for('worker.worker_debug'))

@worker_routes.route('/scale', methods=['POST'])
def force_scale():
    """Force le scaling d'un service via l'orchestrateur"""
    service = request.form.get('service')
    count = request.form.get('count')
    
    if not service or not count:
        flash("Paramètres manquants", "danger")
        return redirect(url_for('worker.worker_debug'))
    
    try:
        count = int(count)
        if count < 1 or count > 10:
            flash("Le nombre doit être entre 1 et 10", "danger")
            return redirect(url_for('worker.worker_debug'))
        
        success, message = orchestrator_client.scale_service(service, count)
        
        if success:
            flash(message, "success")
        else:
            flash(f"Erreur: {message}", "danger")
        
    except Exception as e:
        flash(f"Erreur lors du scaling: {str(e)}", "danger")
    
    return redirect(url_for('worker.worker_debug'))

@worker_routes.route('/autoscaling')
def autoscaling():
    """Affiche et permet de configurer l'auto-scaling"""
    # ...existing code...