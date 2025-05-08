import os
import json
import uuid
import datetime
import time  # Ajout de l'import manquant
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from pymongo import MongoClient
import datetime
import uuid
from image_urls_generator import get_themed_urls, get_themed_queries, get_wikidata_themed_images
from docker_manager import DockerScaler
from orchestrator_client import OrchestratorClient

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Pour les messages flash

# Configuration MongoDB
DB_URL = os.environ.get('DATABASE_URL', 'mongodb://localhost:27017/imagesdb')
client = MongoClient(DB_URL)
db = client.get_database()

# Initialiser le gestionnaire Docker
docker_scaler = DockerScaler()

# Initialiser le client orchestrateur
orchestrator_client = OrchestratorClient()

# Fix the timestamp_to_date template filter to handle both timestamp integers and datetime objects

@app.template_filter('timestamp_to_date')
def timestamp_to_date(value):
    """Converts a timestamp to a formatted date string, handles both int and datetime objects"""
    from datetime import datetime
    
    if value is None:
        return ""
    
    # If the value is already a datetime object
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    
    # If it's a numeric timestamp
    try:
        timestamp = float(value)
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        # If conversion fails, return the original value as string
        return str(value)

@app.route('/')
def index():
    """Page d'accueil du dashboard"""
    # Statistiques générales
    stats = {
        'images_count': db.images.count_documents({}),
        'tagged_images': db.images.count_documents({"tagged": True}),
        'users_count': db.users.count_documents({}),
        'recommendations_count': db.recommendations.count_documents({})
    }
    
    # État des workers
    downloader_tasks = list(db.download_tasks.find().sort('created_at', -1).limit(5))
    tagger_tasks = list(db.tagging_tasks.find().sort('created_at', -1).limit(5))
    recommendation_tasks = list(db.recommendation_tasks.find().sort('created_at', -1).limit(5))
    
    return render_template('index.html', 
                          stats=stats,
                          downloader_tasks=downloader_tasks,
                          tagger_tasks=tagger_tasks,
                          recommendation_tasks=recommendation_tasks)

@app.route('/images')
def images():
    """Affiche les images disponibles"""
    page = int(request.args.get('page', 1))
    per_page = 20
    skip = (page - 1) * per_page
    
    images = list(db.images.find().skip(skip).limit(per_page))
    total = db.images.count_documents({})
    
    return render_template('images.html', 
                          images=images, 
                          page=page, 
                          total=total, 
                          per_page=per_page,
                          total_pages=(total // per_page) + (1 if total % per_page > 0 else 0))

@app.route('/image/<image_id>')
def image_detail(image_id):
    """Détails d'une image spécifique"""
    image = db.images.find_one({"_id": image_id})
    if not image:
        flash("Image non trouvée", "danger")
        return redirect(url_for('images'))
    
    return render_template('image_detail.html', image=image)

@app.route('/images/<image_id>')
def serve_image(image_id):
    """Sert une image depuis le volume partagé"""
    image_path = f"/data/images/{image_id}.jpg"
    
    # Vérifier si l'image existe
    if not os.path.exists(image_path):
        # Retourner une image par défaut ou une erreur 404
        return send_file("static/no-image.jpg", mimetype='image/jpeg')
    
    # Servir l'image
    return send_file(image_path, mimetype='image/jpeg')

@app.route('/users')
def users():
    """Liste des utilisateurs"""
    users = list(db.users.find())
    return render_template('users.html', users=users)

@app.route('/users/<user_id>')
def user_detail(user_id):
    """Détails d'un utilisateur et ses préférences"""
    user = db.users.find_one({"_id": user_id})
    if not user:
        flash("Utilisateur non trouvé", "danger")
        return redirect(url_for('users'))
    
    # Récupérer les likes/dislikes de l'utilisateur
    likes = list(db.user_likes.find({"user_id": user_id, "liked": True}))
    dislikes = list(db.user_likes.find({"user_id": user_id, "liked": False}))
    
    # Récupérer les images correspondantes
    liked_images = []
    for like in likes:
        image = db.images.find_one({"_id": like["image_id"]})
        if image:
            liked_images.append(image)
    
    disliked_images = []
    for dislike in dislikes:
        image = db.images.find_one({"_id": dislike["image_id"]})
        if image:
            disliked_images.append(image)
    
    # Récupérer les recommandations
    recommendations = db.recommendations.find_one({"user_id": user_id})
    recommended_images = []
    if recommendations and "recommendations" in recommendations:
        for rec in recommendations["recommendations"]:
            image = db.images.find_one({"_id": rec["image_id"]})
            if image:
                image["score"] = rec["score"]
                recommended_images.append(image)
    
    return render_template('user_detail.html', 
                          user=user, 
                          liked_images=liked_images,
                          disliked_images=disliked_images,
                          recommended_images=recommended_images)

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

@app.route('/create_user', methods=['GET', 'POST'])
def create_user():
    """Crée un nouvel utilisateur"""
    if request.method == 'POST':
        user_id = request.form.get('user_id') or str(uuid.uuid4())
        name = request.form.get('name')
        
        if not name:
            flash("Le nom est requis", "warning")
            return redirect(url_for('create_user'))
        
        # Préférences de genre et couleur
        genres = request.form.getlist('genres')
        colors = request.form.getlist('colors')
        
        db.users.insert_one({
            "_id": user_id,
            "name": name,
            "preferences": {
                "genres": genres,
                "colors": colors
            },
            "created_at": datetime.datetime.now()
        })
        
        flash(f"Utilisateur {name} créé avec succès", "success")
        return redirect(url_for('users'))
    
    return render_template('create_user.html')

@app.route('/like_image', methods=['POST'])
def like_image():
    """Ajoute un like/dislike à une image"""
    user_id = request.form.get('user_id')
    image_id = request.form.get('image_id')
    liked = request.form.get('liked') == 'true'
    
    if not user_id or not image_id:
        flash("Paramètres manquants", "danger")
        return redirect(url_for('images'))
    
    # Vérifier que l'utilisateur et l'image existent
    user = db.users.find_one({"_id": user_id})
    image = db.images.find_one({"_id": image_id})
    
    if not user or not image:
        flash("Utilisateur ou image non trouvé", "danger")
        return redirect(url_for('images'))
    
    # Ajouter/mettre à jour le like
    db.user_likes.update_one(
        {"user_id": user_id, "image_id": image_id},
        {"$set": {
            "liked": liked,
            "timestamp": datetime.datetime.now()
        }},
        upsert=True
    )
    
    flash(f"Image {'likée' if liked else 'dislikée'} avec succès", "success")
    
    # Rediriger vers la page précédente ou vers les détails de l'utilisateur
    redirect_url = request.form.get('redirect_url') or url_for('user_detail', user_id=user_id)
    return redirect(redirect_url)

@app.route('/image_browser')
def image_browser():
    """Interface de type Tinder pour parcourir les images"""
    user_id = request.args.get('user_id')
    if not user_id:
        flash("Utilisateur requis", "warning")
        return redirect(url_for('users'))
    
    # Récupérer les images que l'utilisateur n'a pas encore évaluées
    user_interactions = list(db.user_likes.find({"user_id": user_id}))
    seen_image_ids = [interaction["image_id"] for interaction in user_interactions]
    
    # Récupérer une image non vue
    next_image = db.images.find_one({
        "_id": {"$nin": seen_image_ids},
        "tagged": True  # On veut des images taguées pour de meilleures décisions
    })
    
    if not next_image:
        flash("Aucune nouvelle image à évaluer", "info")
        return redirect(url_for('user_detail', user_id=user_id))
    
    return render_template('image_browser.html', user_id=user_id, image=next_image)

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

# Ajouter ces routes pour la gestion des workers

@app.route('/workers')
def workers_list():
    """Affiche la liste des workers et leur état"""
    try:
        # Récupérer les données réelles des workers depuis MongoDB
        # Téléchargeurs d'images
        downloader_workers = []
        for worker_id in range(1, 3):  # Nos 2 workers de téléchargement
            worker_info = get_real_worker_info('downloader', worker_id)
            downloader_workers.append(worker_info)
        
        # Taggers d'images
        tagger_workers = []
        for worker_id in range(1, 3):  # Nos 2 workers de tagging
            worker_info = get_real_worker_info('tagger', worker_id)
            tagger_workers.append(worker_info)
        
        # Service de recommandation
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
        import traceback
        traceback.print_exc()
        flash(f"Erreur lors du chargement des informations des workers: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/worker/<worker_type>/<int:worker_id>')
def worker_detail(worker_type, worker_id):
    """Affiche les détails d'un worker spécifique"""
    try:
        # Obtenir uniquement des informations réelles
        worker = get_real_worker_info(worker_type, worker_id)
        
        return render_template('worker_details.html', worker=worker)
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f"Erreur lors du chargement des détails du worker: {str(e)}", "danger")
        return redirect(url_for('workers'))

def get_worker_info(worker_type, worker_id, refresh=False, details=False):
    """Récupère les informations d'un worker, soit simulées soit réelles"""
    try:
        # Toujours utiliser les informations réelles du worker
        return get_real_worker_info(worker_type, worker_id)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des informations réelles du worker: {e}")
        # Fallback vers la version simulée si nécessaire
        return get_simulated_worker_info(worker_type, worker_id, details)

def get_simulated_worker_info(worker_type, worker_id, details=False):
    """Version de secours qui génère des données simulées"""
    # Cette fonction reste inchangée, car c'est votre implémentation originale
    import random
    import time
    from datetime import datetime, timedelta
    
    status_options = ['active', 'idle', 'offline']
    status = random.choice(status_options)
    status_weight = {'active': 0.7, 'idle': 0.2, 'offline': 0.1}
    status = random.choices(status_options, [status_weight[s] for s in status_options])[0]
    
    # Statistiques de base
    stats = {
        "completed_tasks": random.randint(10, 100),
        "success_rate": random.randint(80, 100),
        "avg_processing_time": random.uniform(0.5, 5.0),
        "pending_tasks": random.randint(0, 10)
    }
    
    # Ajout de statistiques spécifiques pour le système de recommandation
    if worker_type == 'recommendation':
        stats["recommendations_count"] = random.randint(50, 200)
        stats["users_count"] = random.randint(5, 20)
    
    # Tâche en cours (si actif)
    current_task = None
    if status == 'active':
        current_task = {
            "id": f"task_{random.randint(1000, 9999)}",
            "progress": random.randint(10, 90),
            "started_at": (datetime.now() - timedelta(minutes=random.randint(1, 30))).strftime("%H:%M:%S")
        }
    
    # Créer/mettre à jour le document worker
    worker_data = {
        "worker_id": worker_id,
        "type": worker_type,
        "status": status,
        "status_color": {"active": "success", "idle": "warning", "offline": "danger"}[status],
        "stats": stats,
        "current_task": current_task,
        "last_update": time.time()
    }
    
    # Si on demande des détails complets, ajouter plus d'informations
    if details:
        worker_data["id"] = worker_id
        worker_data["hostname"] = f"{worker_type}-{worker_id}"
        # Ces détails supplémentaires seraient récupérés du worker réel
    
    # Sauvegarder dans MongoDB
    db[collection_name].update_one(
        {"worker_id": worker_id},
        {"$set": worker_data},
        upsert=True
    )
    
    return worker_data

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
        
        # Formater created_at en toute sécurité
        if "created_at" in task:
            try:
                if isinstance(task["created_at"], datetime.datetime):
                    formatted_task["created_at"] = task["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    formatted_task["created_at"] = datetime.datetime.fromtimestamp(float(task["created_at"])).strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_task["created_at"] = str(task["created_at"])
        
        # Formater completed_at en toute sécurité
        if "completed_at" in task:
            try:
                if isinstance(task["completed_at"], datetime.datetime):
                    formatted_task["completed_at"] = task["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    formatted_task["completed_at"] = datetime.datetime.fromtimestamp(float(task["completed_at"])).strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_task["completed_at"] = str(task["completed_at"])
        
        # Corriger les valeurs de type et y ajouter les informations de URL/image IDs si disponibles
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

@app.route('/tag_image', methods=['POST'])
def tag_image():
    """Déclenche manuellement le tagging d'une image"""
    image_id = request.form.get('image_id')
    if not image_id:
        flash("ID d'image requis", "danger")
        return redirect(url_for('images'))
    
    # Vérifier si l'image existe
    image = db.images.find_one({"_id": image_id})
    if not image:
        flash("Image non trouvée", "danger")
        return redirect(url_for('images'))
    
    # Créer une tâche de tagging spécifique pour cette image
    worker_id = 1  # Assigner au worker 1 par défaut
    
    # Vérifier s'il y a déjà une tâche pour cette image
    existing_task = db.tagging_tasks.find_one({
        "$or": [
            {"image_ids": image_id, "status": "pending"},
            {"image_ids": image_id, "status": "in_progress"}
        ]
    })
    
    if existing_task:
        flash("Une tâche de tagging est déjà en cours pour cette image", "warning")
    else:
        # Marquer l'image comme non taguée pour forcer le retagging
        db.images.update_one(
            {"_id": image_id},
            {"$set": {"tagged": False}}
        )
        
        # Créer une nouvelle tâche pour cette image
        task_id = db.tagging_tasks.insert_one({
            "_id": f"manual_{image_id}_{int(time.time())}",
            "worker_id": worker_id,
            "image_ids": [image_id],
            "status": "pending",
            "created_at": time.time(),
            "priority": "high",  # Priorité haute pour le tagging manuel
            "manual": True  # Indiquer que c'est une tâche manuelle
        }).inserted_id
        
        flash(f"Tâche de tagging créée pour l'image {image_id}", "success")
    
    # Rediriger vers les détails de l'image
    return redirect(url_for('image_detail', image_id=image_id))

@app.route('/tag_all_images', methods=['POST'])
def tag_all_images():
    """Déclenche le tagging de toutes les images non taguées"""
    # Compter les images non taguées
    untagged_count = db.images.count_documents({"tagged": {"$ne": True}})
    
    if untagged_count == 0:
        flash("Aucune image non taguée trouvée", "info")
        return redirect(url_for('images'))
    
    # Récupérer tous les IDs d'images non taguées
    untagged_images = list(db.images.find({"tagged": {"$ne": True}}, {"_id": 1}))
    untagged_ids = [img["_id"] for img in untagged_images]
    
    # Diviser en deux groupes pour les deux workers
    half = len(untagged_ids) // 2
    worker1_ids = untagged_ids[:half + (1 if len(untagged_ids) % 2 == 1 else 0)]
    worker2_ids = untagged_ids[half + (1 if len(untagged_ids) % 2 == 1 else 0):]
    
    # Créer des tâches de tagging
    tasks_created = 0
    
    if worker1_ids:
        db.tagging_tasks.insert_one({
            "_id": f"manual_batch1_{int(time.time())}",
            "worker_id": 1,
            "image_ids": worker1_ids,
            "status": "pending",
            "created_at": time.time(),
            "manual": True
        })
        tasks_created += 1
    
    if worker2_ids:
        db.tagging_tasks.insert_one({
            "_id": f"manual_batch2_{int(time.time())}",
            "worker_id": 2,
            "image_ids": worker2_ids,
            "status": "pending",
            "created_at": time.time(),
            "manual": True
        })
        tasks_created += 1
    
    flash(f"Tâches de tagging créées pour {untagged_count} images (réparties entre {tasks_created} workers)", "success")
    return redirect(url_for('images'))

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
        
        # Formater created_at en toute sécurité
        if "created_at" in task:
            try:
                if isinstance(task["created_at"], datetime.datetime):
                    formatted_task["created_at"] = task["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    formatted_task["created_at"] = datetime.datetime.fromtimestamp(float(task["created_at"])).strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_task["created_at"] = str(task["created_at"])
        
        # Formater completed_at en toute sécurité
        if "completed_at" in task:
            try:
                if isinstance(task["completed_at"], datetime.datetime):
                    formatted_task["completed_at"] = task["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    formatted_task["completed_at"] = datetime.datetime.fromtimestamp(float(task["completed_at"])).strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_task["completed_at"] = str(task["completed_at"])
        
        # Corriger les valeurs de type et y ajouter les informations de URL/image IDs si disponibles
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

@app.route('/autoscaling')
def autoscaling():
    """Affiche et permet de configurer l'auto-scaling"""
    # Récupérer les stats des workers actuels
    downloader_count = 0
    tagger_count = 0
    
    # Compter les workers actifs
    try:
        # Compter les downloaders
        downloaders = db.download_tasks.distinct("worker_id")
        downloader_count = len(downloaders)
        
        # Compter les taggers
        taggers = db.tagging_tasks.distinct("worker_id")  
        tagger_count = len(taggers)
    except Exception as e:
        flash(f"Erreur lors du comptage des workers: {e}", "danger")
    
    # Récupérer les tâches en attente
    pending_downloads = db.download_tasks.count_documents({"status": "pending"})
    pending_tagging = db.tagging_tasks.count_documents({"status": "pending"})
    
    # Compter les URLs et images en attente
    pending_urls = 0
    for task in db.download_tasks.find({"status": "pending"}):
        pending_urls += len(task.get('urls', []))
    
    pending_images = 0
    for task in db.tagging_tasks.find({"status": "pending"}):
        pending_images += len(task.get('image_ids', []))
    
    # Calculer les workers suggérés
    images_per_worker = 20  # Configurable
    max_workers = 5  # Maximum
    
    suggested_downloaders = max(1, min(max_workers, (pending_urls + images_per_worker - 1) // images_per_worker))
    suggested_taggers = max(1, min(max_workers, (pending_images + images_per_worker - 1) // images_per_worker))
    
    return render_template('autoscaling.html',
                          downloader_count=downloader_count,
                          tagger_count=tagger_count,
                          pending_downloads=pending_downloads,
                          pending_tagging=pending_tagging,
                          pending_urls=pending_urls,
                          pending_images=pending_images,
                          suggested_downloaders=suggested_downloaders,
                          suggested_taggers=suggested_taggers,
                          images_per_worker=images_per_worker)

@app.route('/scale_service', methods=['POST'])
def scale_service():
    """Ajuste l'échelle d'un service manuellement"""
    service = request.form.get('service')
    count = int(request.form.get('count', 1))
    
    # Vérifier les paramètres
    if service not in ['image_downloader', 'image_tagger'] or count < 1 or count > 10:
        flash("Paramètres invalides", "danger")
        return redirect(url_for('autoscaling'))
    
    try:
        # Lancer une commande docker-compose via subprocess
        import subprocess
        cmd = f"docker-compose -f /app/docker-compose.yml up -d --scale {service}={count} {service}"
        result = subprocess.run(cmd, shell=True, check=True)
        flash(f"Service {service} mis à l'échelle à {count} instances", "success")
    except Exception as e:
        flash(f"Erreur lors de la mise à l'échelle: {e}", "danger")
    
    return redirect(url_for('autoscaling'))

# Ajouter ces nouvelles routes

@app.route('/worker_debug')
def worker_debug():
    """Page de debugging pour voir l'état des workers et des conteneurs Docker"""
    try:
        # Récupérer les données des conteneurs depuis MongoDB (remplies par l'autoscaler)
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
        return redirect(url_for('index'))

@app.route('/redistribute_tasks', methods=['POST'])
def redistribute_tasks():
    """Route pour forcer la redistribution des tâches en attente"""
    try:
        # Récupérer le nombre actuel de conteneurs pour chaque service
        from pymongo import MongoClient
        client = MongoClient(os.environ.get('DATABASE_URL', 'mongodb://database:27017/imagesdb'))
        db = client.get_database()
        
        # Compter les downloaders et taggers disponibles
        downloaders = set()
        for task in db.download_tasks.find():
            worker_id = task.get("worker_id")
            if worker_id:
                downloaders.add(worker_id)
        
        taggers = set()
        for task in db.tagging_tasks.find():
            worker_id = task.get("worker_id")
            if worker_id:
                taggers.add(worker_id)
        
        downloader_count = len(downloaders)
        tagger_count = len(taggers)
        
        if downloader_count == 0:
            downloader_count = 1
        if tagger_count == 0:
            tagger_count = 1
        
        # Redistribuer les tâches de téléchargement en attente
        pending_download_tasks = list(db.download_tasks.find({"status": "pending"}))
        for i, task in enumerate(pending_download_tasks):
            new_worker_id = (i % downloader_count) + 1
            db.download_tasks.update_one(
                {"_id": task["_id"]},
                {"$set": {"worker_id": new_worker_id}}
            )
        
        # Redistribuer les tâches de tagging en attente
        pending_tagging_tasks = list(db.tagging_tasks.find({"status": "pending"}))
        for i, task in enumerate(pending_tagging_tasks):
            new_worker_id = (i % tagger_count) + 1
            db.tagging_tasks.update_one(
                {"_id": task["_id"]},
                {"$set": {"worker_id": new_worker_id}}
            )
        
        flash(f"Redistribution effectuée: {len(pending_download_tasks)} tâches de téléchargement et {len(pending_tagging_tasks)} tâches de tagging", "success")
        return redirect(url_for('worker_debug'))
    except Exception as e:
        flash(f"Erreur lors de la redistribution: {str(e)}", "danger")
        return redirect(url_for('worker_debug'))

@app.route('/force_scale', methods=['POST'])
def force_scale():
    """Force le scaling d'un service via l'orchestrateur"""
    service = request.form.get('service')
    count = request.form.get('count')
    
    if not service or not count:
        flash("Paramètres manquants", "danger")
        return redirect(url_for('worker_debug'))
    
    try:
        count = int(count)
        if count < 1 or count > 10:
            flash("Le nombre doit être entre 1 et 10", "danger")
            return redirect(url_for('worker_debug'))
        
        success, message = orchestrator_client.scale_service(service, count)
        
        if success:
            flash(message, "success")
        else:
            flash(f"Erreur: {message}", "danger")
        
    except Exception as e:
        flash(f"Erreur lors du scaling: {str(e)}", "danger")
    
    return redirect(url_for('worker_debug'))

@app.route('/task_debug/<task_id>')
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
        return redirect(url_for('worker_debug'))
    
    # Récupérer des informations sur le worker
    worker_id = task.get("worker_id")
    worker_info = {}
    
    service_name = "image_downloader" if task_type == "download" else "image_tagger"
    
    # Rechercher le conteneur Docker pour ce worker
    container_info = None
    container_logs = None
    container_status = "unknown"
    
    # Vérifier si Docker est disponible
    try:
        import docker
        docker_client = docker.from_env()
        
        # Chercher le conteneur
        containers = docker_client.containers.list(
            all=True,
            filters={"label": [f"com.docker.compose.service={service_name}"]}
        )
        
        for container in containers:
            env_vars = container.attrs.get('Config', {}).get('Env', [])
            for env in env_vars:
                if env == f"WORKER_ID={worker_id}":
                    container_info = {
                        "id": container.id[:12],
                        "name": container.name,
                        "status": container.status
                    }
                    container_status = container.status
                    # Récupérer les logs du conteneur (1000 derniers caractères)
                    try:
                        logs = container.logs().decode('utf-8')
                        container_logs = logs[-2000:] if logs else "Pas de logs"
                    except Exception as e:
                        container_logs = f"Erreur lors de la récupération des logs: {e}"
                    break
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
            "action": f"/redistribute_task/{task_id}"
        },
        {
            "id": "restart_container",
            "name": "Redémarrer le conteneur",
            "description": "Redémarre le conteneur associé à ce worker",
            "action": f"/restart_container/{service_name}/{worker_id}"
        },
        {
            "id": "create_container",
            "name": "Créer un nouveau conteneur",
            "description": "Crée un nouveau conteneur pour ce worker",
            "action": f"/create_container/{service_name}/{worker_id}"
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

@app.route('/redistribute_task/<task_id>', methods=['POST'])
def redistribute_task(task_id):
    """Réassigne une tâche à un autre worker via l'orchestrateur"""
    success, message = orchestrator_client.redistribute_task(task_id)
    
    if success:
        flash(message, "success")
    else:
        flash(f"Erreur: {message}", "danger")
    
    return redirect(url_for('task_debug', task_id=task_id))

@app.route('/restart_container/<service_name>/<int:worker_id>', methods=['POST'])
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
        return redirect(url_for('task_debug', task_id=task_id))
    else:
        return redirect(url_for('worker_debug'))

@app.route('/create_container/<service_name>/<int:worker_id>', methods=['POST'])
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
        return redirect(url_for('task_debug', task_id=task_id))
    else:
        return redirect(url_for('worker_debug'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
