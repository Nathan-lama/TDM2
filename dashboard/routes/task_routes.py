from flask import Blueprint, render_template, request, redirect, url_for, flash
from config import db, orchestrator_client
from image_urls_generator import get_wikidata_themed_images, get_themed_queries
import uuid
import datetime
import time
import os
import logging

# Configurer le logger
debug_logger = logging.getLogger('debug')
debug_logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('DEBUG: %(message)s'))
debug_logger.addHandler(handler)

task_routes = Blueprint('task', __name__, url_prefix='/tasks')

@task_routes.route('/create', methods=['GET', 'POST'])
def create_task():
    """Crée une nouvelle tâche"""
    if request.method == 'POST':
        task_type = request.form.get('task_type')
        
        if task_type == 'download':
            # Créer une tâche de téléchargement
            urls = request.form.get('urls', '').strip().split('\n')
            urls = [url.strip() for url in urls if url.strip()]
            
            if not urls:
                flash("Veuillez fournir au moins une URL", "warning")
                return redirect(url_for('task.create_task'))
            
            # Diviser les URLs entre les workers de manière équilibrée
            
            worker1_urls = urls[::2]  # Indices pairs
            worker2_urls = urls[1::2]  # Indices impairs
            
            if worker1_urls:
                db.download_tasks.insert_one({
                    "_id": str(uuid.uuid4()),
                    "worker_id": 1,
                    "urls": worker1_urls,
                    "status": "pending",
                    "created_at": datetime.datetime.now()
                })
            
            if worker2_urls:
                db.download_tasks.insert_one({
                    "_id": str(uuid.uuid4()),
                    "worker_id": 2,
                    "urls": worker2_urls,
                    "status": "pending",
                    "created_at": datetime.datetime.now()
                })
            
            flash(f"{len(urls)} URLs ajoutées pour téléchargement", "success")
            
        elif task_type == 'tagging':
            # ...existing code for tagging task...
            pass
            
        elif task_type == 'recommendation':
            # ...existing code for recommendation task...
            pass
        
        return redirect(url_for('main.index'))
    
    return render_template('create_task.html')

@task_routes.route('/batch_download', methods=['GET', 'POST'])
def batch_download():
    """Télécharge un lot d'images thématiques depuis WikiData"""
    if request.method == 'POST':
        # Récupérer les paramètres du formulaire
        theme = request.form.get('theme', 'nature')
        count = int(request.form.get('count', 50))
        auto_scale = request.form.get('auto_scale', 'yes') == 'yes'  # Activer par défaut
        
        # Option pour nettoyer la base de données
        clean_db = request.form.get('clean_db') == 'yes'
        
        if clean_db:
            # Créer une tâche de nettoyage explicite
            clean_task_id = str(uuid.uuid4())
            db.download_tasks.insert_one({
                "_id": clean_task_id,
                "worker_id": 1,
                "action": "clean",
                "clean_all": True,  # Flag explicite pour tout nettoyer
                "status": "pending", 
                "created_at": time.time(),
                "priority": "high"
            })
            
            # Effectuer le nettoyage en direct dans MongoDB
            try:
                # Compter avant suppression
                image_count = db.images.count_documents({})
                
                # Supprimer les collections principales
                db.images.delete_many({})
                db.tags.delete_many({})
                db.user_likes.delete_many({})
                db.recommendations.delete_many({})
                
                flash(f"Base de données nettoyée: {image_count} images supprimées", "success")
            except Exception as e:
                flash(f"Erreur lors du nettoyage de la base de données: {str(e)}", "danger")
        
        # Récupérer des images thématiques depuis WikiData
        urls = get_wikidata_themed_images(theme, count)
        
        if not urls:
            flash(f"Aucune image trouvée pour le thème '{theme}'", "warning")
            return redirect(url_for('task.batch_download'))
        
        # Afficher le nombre réel d'URLs trouvées
        if len(urls) < count:
            flash(f"Seulement {len(urls)} images trouvées sur les {count} demandées", "info")
        
        # Définir le nombre d'images par worker de manière dynamique
        IMAGES_PER_WORKER = 10  # Idéalement 10 images par worker
        
        # Calculer le nombre optimal de workers en fonction du nombre d'images
        optimal_worker_count = max(1, min(5, (len(urls) + IMAGES_PER_WORKER - 1) // IMAGES_PER_WORKER))
        
        # Utiliser un seul worker pour moins de 10 images
        if len(urls) <= IMAGES_PER_WORKER:
            worker_count = 1
        else:
            worker_count = optimal_worker_count
        
        # Afficher le raisonnement de scaling
        scaling_explanation = f"Autoscaling: {len(urls)} images ÷ {IMAGES_PER_WORKER} images par worker = {worker_count} worker{'s' if worker_count > 1 else ''}"
        flash(scaling_explanation, "info")
        
        # Effectuer l'auto-scaling
        if auto_scale:
            try:
                success, message = orchestrator_client.scale_service("image_downloader", worker_count)
                if success:
                    flash(f"Service image_downloader scaled à {worker_count} instance{'s' if worker_count > 1 else ''}", "success")
                else:
                    flash(f"Échec du scaling automatique: {message}", "danger")
            except Exception as e:
                flash(f"Erreur lors du scaling: {str(e)}", "danger")
        
        # Distribution optimisée des URLs entre les workers
        tasks_created = 0
        
        # Calculer équitablement la répartition des URLs
        base_urls_per_worker = len(urls) // worker_count
        extra_urls = len(urls) % worker_count
        
        start_idx = 0
        for worker_id in range(1, worker_count + 1):
            # Calculer le nombre d'URLs pour ce worker (distribution équitable)
            worker_urls_count = base_urls_per_worker + (1 if worker_id <= extra_urls else 0)
            
            # Extraire les URLs pour ce worker
            worker_urls = urls[start_idx:start_idx + worker_urls_count]
            start_idx += worker_urls_count
            
            if worker_urls:
                task_id = str(uuid.uuid4())
                db.download_tasks.insert_one({
                    "_id": task_id,
                    "worker_id": worker_id,
                    "urls": worker_urls,
                    "status": "pending",
                    "created_at": time.time(),
                    "theme": theme,
                    "urls_count": len(worker_urls)
                })
                tasks_created += 1
                flash(f"Worker {worker_id}: {len(worker_urls)} images à télécharger (Tâche: {task_id[:6]}...)", "info")
        
        # Message récapitulatif
        summary = (f"{len(urls)} images du thème '{theme}' réparties entre {tasks_created} worker"
                 f"{'s' if tasks_created > 1 else ''}")
        flash(summary, "success")
        
        return redirect(url_for('main.index'))
    
    # GET request - show the form
    # Récupérer les thèmes disponibles
    themes = get_themed_queries().keys()
    
    # Vérifier si l'auto-scaling est disponible
    auto_scale_available = True  # Toujours disponible maintenant
    current_workers = orchestrator_client.get_current_scale() if orchestrator_client.is_connected() else 1
    
    return render_template('batch_download.html', 
                         themes=themes, 
                         auto_scale_available=auto_scale_available,
                         current_workers=current_workers)

@task_routes.route('/clear_database', methods=['GET', 'POST'])
def clear_database():
    """Supprime TOUTES les images de manière simple et efficace"""
    debug_logger.debug("🔍 DÉBUT de clear_database() avec méthode %s", request.method)
    
    if request.method == 'POST':
        try:
            debug_logger.debug("🔍 SUPPRESSION des collections...")
            # 1. SUPPRIMER TOUTES LES DONNÉES VIA DELETE_MANY (plus sûr que drop_collection)
            image_count = db.images.count_documents({})
            tag_count = db.tags.count_documents({})
            like_count = db.user_likes.count_documents({})
            rec_count = db.recommendations.count_documents({})
            
            debug_logger.debug(f"🔍 Nombres avant suppression: {image_count} images, {tag_count} tags, {like_count} likes")
            
            # Utiliser delete_many avec un filtre vide pour tout supprimer 
            # (plus sûr que drop_collection qui peut causer des problèmes d'index)
            db.images.delete_many({})
            db.tags.delete_many({})
            db.user_likes.delete_many({})
            db.recommendations.delete_many({})
            
            # Vérification après suppression
            remaining_images = db.images.count_documents({})
            debug_logger.debug(f"🔍 Après suppression: {remaining_images} images restantes")
            
            # 2. ANNULER TOUTES LES TÂCHES EN COURS
            deleted_downloads = db.download_tasks.delete_many({"status": {"$in": ["pending", "in_progress"]}}).deleted_count
            deleted_taggings = db.tagging_tasks.delete_many({"status": {"$in": ["pending", "in_progress"]}}).deleted_count
            
            debug_logger.debug(f"🔍 Tâches supprimées: {deleted_downloads} téléchargements, {deleted_taggings} taggings")
            
            flash(f"✅ Base de données nettoyée: {image_count} images, {tag_count} tags supprimés", "success")
            
            # 3. SUPPRIMER LES FICHIERS IMAGES
            try:
                import os
                import glob
                # Nettoyer les fichiers d'image
                image_path = "/data/images"
                debug_logger.debug(f"🔍 Tentative de suppression des fichiers dans {image_path}")
                
                if os.path.exists(image_path):
                    files = glob.glob(f"{image_path}/*.jpg") + glob.glob(f"{image_path}/*.jpeg") + glob.glob(f"{image_path}/*.png")
                    debug_logger.debug(f"🔍 {len(files)} fichiers trouvés")
                    
                    for f in files:
                        try:
                            os.remove(f)
                            debug_logger.debug(f"🔍 Supprimé: {f}")
                        except Exception as file_err:
                            debug_logger.debug(f"🔍 Erreur suppression {f}: {file_err}")
                    
                    flash(f"✅ {len(files)} fichiers d'images supprimés du disque", "success")
                else:
                    debug_logger.debug(f"🔍 Dossier {image_path} non trouvé")
                    flash(f"⚠️ Dossier d'images non trouvé", "warning")
            except Exception as e:
                debug_logger.debug(f"🔍 Erreur suppression fichiers: {str(e)}")
                flash(f"Erreur lors de la suppression des fichiers: {str(e)}", "warning")
            
            # 4. REDÉMARRER LES WORKERS
            try:
                # Arrêter tous les workers
                debug_logger.debug("🔍 Tentative d'arrêt des workers")
                result1 = orchestrator_client.scale_service("image_downloader", 0)
                result2 = orchestrator_client.scale_service("image_tagger", 0)
                
                debug_logger.debug(f"🔍 Résultat arrêt: downloader={result1}, tagger={result2}")
                
                # Attendre un peu
                time.sleep(1)
                
                # Redémarrer un worker minimal
                debug_logger.debug("🔍 Redémarrage d'un worker")
                result3 = orchestrator_client.scale_service("image_downloader", 1)
                debug_logger.debug(f"🔍 Résultat redémarrage: {result3}")
                
                flash("✅ Les workers ont été redémarrés", "success")
            except Exception as e:
                debug_logger.debug(f"🔍 Erreur redémarrage workers: {str(e)}")
                flash(f"Erreur lors du redémarrage des workers: {str(e)}", "warning")
                
        except Exception as e:
            debug_logger.debug(f"🔍 ERREUR GLOBALE: {str(e)}")
            flash(f"❌ Erreur lors du nettoyage: {str(e)}", "danger")
        
        debug_logger.debug("🔍 FIN clear_database: redirection vers l'accueil")
        return redirect(url_for('main.index'))
    
    # Méthode GET - rediriger vers l'accueil
    debug_logger.debug("🔍 Méthode GET reçue, redirection vers l'accueil")
    return redirect(url_for('main.index'))

@task_routes.route('/debug/<task_id>')
def task_debug(task_id):
    """Page de debug pour une tâche spécifique"""
    # Trouver la tâche
    task = db.download_tasks.find_one({"_id": task_id})
    task_type = "download"
    
    if not task:
        task = db.tagging_tasks.find_one({"_id": task_id})
        task_type = "tagging"
    
    if not task:
        flash("Tâche non trouvée", "danger")
        return redirect(url_for('worker.worker_debug'))
    
    # Récupérer des informations sur le worker
    worker_id = task.get("worker_id")
    
    service_name = "image_downloader" if task_type == "download" else "image_tagger"
    
    # Rechercher le conteneur Docker pour ce worker
    container_info = None
    container_logs = None
    container_status = "unknown"
    
    # Vérifier si Docker est disponible via l'orchestrateur
    try:
        # Obtenir les informations du conteneur via l'orchestrateur client
        container_info = orchestrator_client.get_container_info(service_name, worker_id)
        if container_info:
            container_status = container_info.get("status", "unknown")
            container_logs = orchestrator_client.get_container_logs(service_name, worker_id, 200)
    except Exception as e:
        container_logs = f"Erreur lors de la connexion à Docker: {e}"
    
    # Vérifier si le worker existe dans la BDD
    worker_tasks_completed = 0
    if task_type == "download":
        worker_tasks_completed = db.download_tasks.count_documents({"worker_id": worker_id, "status": "completed"})
    else:
        worker_tasks_completed = db.tagging_tasks.count_documents({"worker_id": worker_id, "status": "completed"})
    
    # Obtenir la date de la dernière tâche complétée par ce worker
    last_completed_task = None
    if task_type == "download":
        last_task = db.download_tasks.find_one({"worker_id": worker_id, "status": "completed"}, sort=[("completed_at", -1)])
    else:
        last_task = db.tagging_tasks.find_one({"worker_id": worker_id, "status": "completed"}, sort=[("completed_at", -1)])
    
    last_activity = None
    if last_task and "completed_at" in last_task:
        from datetime import datetime
        last_activity = datetime.fromtimestamp(last_task["completed_at"]).strftime('%Y-%m-%d %H:%M:%S')
    
    # Diagnostic de problèmes courants
    diagnostics = []
    
    if container_status != "running":
        diagnostics.append({
            "type": "error",
            "message": f"Le conteneur du worker n'est pas en cours d'exécution (statut: {container_status})",
            "solution": "Redémarrez le conteneur ou créez-en un nouveau pour ce worker"
        })
    
    if worker_tasks_completed == 0:
        diagnostics.append({
            "type": "warning",
            "message": "Ce worker n'a jamais complété de tâche",
            "solution": "Vérifiez que le worker est correctement configuré"
        })
    
    if last_activity is None:
        diagnostics.append({
            "type": "warning",
            "message": "Aucune activité récente détectée pour ce worker",
            "solution": "Vérifiez que le worker est opérationnel et peut accéder à la base de données"
        })
    
    # Vérifier si la tâche est bien assignée à un worker existant
    if container_info is None:
        diagnostics.append({
            "type": "error",
            "message": f"Aucun conteneur trouvé pour le worker {worker_id}",
            "solution": "Réassignez cette tâche à un worker actif ou créez un nouveau worker avec cet ID"
        })
    
    # Actions correctives possibles
    actions = [
        {
            "id": "redistribute",
            "name": "Réassigner la tâche",
            "description": "Réassigne cette tâche à un autre worker actif",
            "action": f"/tasks/redistribute/{task_id}"
        },
        {
            "id": "restart_container",
            "name": "Redémarrer le conteneur",
            "description": "Redémarre le conteneur associé à ce worker",
            "action": f"/workers/restart/{service_name}/{worker_id}"
        },
        {
            "id": "create_container",
            "name": "Créer un nouveau conteneur",
            "description": "Crée un nouveau conteneur pour ce worker",
            "action": f"/workers/create/{service_name}/{worker_id}"
        }
    ]
    
    return render_template('task_debug.html', 
                          task=task,
                          task_type=task_type,
                          worker_id=worker_id,
                          worker_tasks_completed=worker_tasks_completed,
                          last_activity=last_activity,
                          container_info=container_info,
                          container_logs=container_logs,
                          diagnostics=diagnostics,
                          actions=actions)

@task_routes.route('/redistribute/<task_id>', methods=['POST'])
def redistribute_task(task_id):
    """Réassigne une tâche à un autre worker via l'orchestrateur"""
    # Si nous sommes en mode fallback, implémenter un mécanisme direct de redistribution
    if orchestrator_client.fallback_mode:
        try:
            # Déterminer le type de tâche
            task = db.download_tasks.find_one({"_id": task_id})
            collection_name = "download_tasks"
            service_name = "image_downloader"
            
            if not task:
                task = db.tagging_tasks.find_one({"_id": task_id})
                collection_name = "tagging_tasks"
                service_name = "image_tagger"
                
            if not task:
                flash("Tâche non trouvée", "danger")
                return redirect(url_for('task.task_debug', task_id=task_id))
            
            # Récupérer l'ID worker actuel
            current_worker_id = task.get("worker_id", 1)
            
            # Choisir un worker différent (simplement alterner entre 1 et 2)
            new_worker_id = 2 if current_worker_id == 1 else 1
            
            # Mettre à jour la tâche avec le nouveau worker_id
            db[collection_name].update_one(
                {"_id": task_id},
                {"$set": {"worker_id": new_worker_id}}
            )
            
            flash(f"Tâche réassignée au worker {new_worker_id} (mode direct)", "success")
            return redirect(url_for('task.task_debug', task_id=task_id))
        except Exception as e:
            flash(f"Erreur lors de la réassignation de la tâche: {str(e)}", "danger")
            return redirect(url_for('task.task_debug', task_id=task_id))
    
    # Utiliser l'orchestrateur si disponible
    success, message = orchestrator_client.redistribute_task(task_id)
    
    if success:
        flash(message, "success")
    else:
        flash(f"Erreur: {message}", "danger")
    
    return redirect(url_for('task.task_debug', task_id=task_id))