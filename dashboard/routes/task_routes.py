import uuid
import datetime
import time
from flask import render_template, request, redirect, url_for, flash
from app import app, db, docker_scaler
from image_urls_generator import get_themed_queries, get_wikidata_themed_images

@app.route('/create_task', methods=['GET', 'POST'])
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
                return redirect(url_for('create_task'))
            
            # Diviser les URLs entre les téléchargeurs
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
            # Créer une tâche de tagging pour les images non taguées
            untagged_images = list(db.images.find({"tagged": {"$ne": True}}, {"_id": 1}))
            untagged_ids = [img["_id"] for img in untagged_images]
            
            if not untagged_ids:
                flash("Aucune image non taguée trouvée", "warning")
                return redirect(url_for('create_task'))
            
            # Diviser les images entre les taggers
            worker1_images = untagged_ids[::2]  # Indices pairs
            worker2_images = untagged_ids[1::2]  # Indices impairs
            
            if worker1_images:
                db.tagging_tasks.insert_one({
                    "_id": str(uuid.uuid4()),
                    "worker_id": 1,
                    "image_ids": worker1_images,
                    "status": "pending",
                    "created_at": datetime.datetime.now()
                })
            
            if worker2_images:
                db.tagging_tasks.insert_one({
                    "_id": str(uuid.uuid4()),
                    "worker_id": 2,
                    "image_ids": worker2_images,
                    "status": "pending",
                    "created_at": datetime.datetime.now()
                })
            
            flash(f"{len(untagged_ids)} images ajoutées pour tagging", "success")
            
        elif task_type == 'recommendation':
            # Créer une tâche de recommandation
            users = list(db.users.find({}, {"_id": 1}))
            user_ids = [user["_id"] for user in users]
            
            if not user_ids:
                flash("Aucun utilisateur trouvé", "warning")
                return redirect(url_for('create_task'))
            
            db.recommendation_tasks.insert_one({
                "_id": str(uuid.uuid4()),
                "user_ids": user_ids,
                "status": "pending",
                "created_at": datetime.datetime.now()
            })
            
            flash(f"Tâche de recommandation créée pour {len(user_ids)} utilisateurs", "success")
        
        return redirect(url_for('index'))
    
    return render_template('create_task.html')

@app.route('/batch_download', methods=['GET', 'POST'])
def batch_download():
    """Télécharge un lot d'images thématiques depuis WikiData"""
    if request.method == 'POST':
        # Récupérer les paramètres du formulaire
        theme = request.form.get('theme', 'nature')
        count = int(request.form.get('count', 50))
        auto_scale = request.form.get('auto_scale') == 'yes'
        
        # Option pour nettoyer la base de données
        clean_db = request.form.get('clean_db') == 'yes'
        
        if clean_db:
            # Créer une tâche de nettoyage
            db.download_tasks.insert_one({
                "_id": str(uuid.uuid4()),
                "worker_id": 1,  # Assigner au worker 1
                "action": "clean",
                "status": "pending",
                "created_at": datetime.datetime.now()
            })
            flash("Tâche de nettoyage de la base de données créée", "info")
        
        # Récupérer des images thématiques depuis WikiData
        urls = get_wikidata_themed_images(theme, count)
        
        if not urls:
            flash(f"Aucune image trouvée pour le thème '{theme}'", "warning")
            return redirect(url_for('batch_download'))
        
        # Si auto-scaling est activé
        worker_count = 2  # Valeur par défaut
        
        if auto_scale and docker_scaler.is_connected():
            # Calculer le nombre optimal de workers
            worker_count = docker_scaler.calculate_optimal_workers(len(urls))
            
            # Scaler le service
            if docker_scaler.scale_service(worker_count):
                flash(f"Service image_downloader scaled à {worker_count} instances", "success")
            else:
                flash("Échec du scaling automatique des conteneurs", "danger")
                worker_count = docker_scaler.get_current_scale() or 2
        
        # Distribuer les URLs entre les workers
        urls_per_worker = len(urls) // worker_count
        extra_urls = len(urls) % worker_count
        
        start_idx = 0
        tasks_created = 0
        
        for worker_id in range(1, worker_count + 1):
            # Calculer le nombre d'URLs pour ce worker
            worker_urls_count = urls_per_worker + (1 if worker_id <= extra_urls else 0)
            
            # Extraire les URLs pour ce worker
            worker_urls = urls[start_idx:start_idx + worker_urls_count]
            start_idx += worker_urls_count
            
            if worker_urls:
                db.download_tasks.insert_one({
                    "_id": str(uuid.uuid4()),
                    "worker_id": worker_id,
                    "urls": worker_urls,
                    "status": "pending",
                    "created_at": datetime.datetime.now(),
                    "theme": theme
                })
                tasks_created += 1
        
        flash(f"{len(urls)} images du thème '{theme}' réparties entre {tasks_created} workers", "success")
        return redirect(url_for('index'))
    
    # Récupérer les thèmes disponibles depuis WikiData
    themes = get_themed_queries().keys()
    
    # Vérifier si l'auto-scaling est disponible
    auto_scale_available = docker_scaler.is_connected()
    current_workers = docker_scaler.get_current_scale() if auto_scale_available else 2
    
    return render_template('batch_download.html', 
                           themes=themes, 
                           auto_scale_available=auto_scale_available,
                           current_workers=current_workers)

@app.route('/clear_database', methods=['POST'])
def clear_database():
    """Supprime toutes les images de la base de données"""
    # Créer une tâche de nettoyage à envoyer au image_downloader
    db.download_tasks.insert_one({
        "_id": str(uuid.uuid4()),
        "worker_id": 1,  # Assigner au worker 1
        "action": "clean",
        "status": "pending",
        "created_at": datetime.datetime.now()
    })
    
    flash("Tâche de nettoyage de la base de données créée - toutes les images seront supprimées", "warning")
    return redirect(url_for('index'))
