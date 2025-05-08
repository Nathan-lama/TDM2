from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from config import db
import os
import uuid
import time
import datetime

# Créer le blueprint sans préfixe
image_routes = Blueprint('image', __name__)

# Ajouter une route avec et sans slash final
@image_routes.route('/images')
@image_routes.route('/images/')
def list_images():
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

@image_routes.route('/image/<image_id>')
def image_detail(image_id):
    """Détails d'une image spécifique"""
    image = db.images.find_one({"_id": image_id})
    if not image:
        flash("Image non trouvée", "danger")
        return redirect(url_for('image.list_images'))
    
    return render_template('image_detail.html', image=image)

# Ajouter une route spécifique pour servir les images
@image_routes.route('/images/<image_id>')
def serve_image(image_id):
    """Sert une image depuis le volume partagé"""
    image_path = f"/data/images/{image_id}.jpg"
    
    # Vérifier si l'image existe
    if not os.path.exists(image_path):
        # Retourner une image par défaut
        return send_file("static/no-image.jpg", mimetype='image/jpeg')
    
    # Servir l'image
    return send_file(image_path, mimetype='image/jpeg')

@image_routes.route('/tag', methods=['POST'])
def tag_image():
    """Déclenche manuellement le tagging d'une image"""
    image_id = request.form.get('image_id')
    if not image_id:
        flash("ID d'image requis", "danger")
        return redirect(url_for('image.list_images'))
    
    # Vérifier si l'image existe
    image = db.images.find_one({"_id": image_id})
    if not image:
        flash("Image non trouvée", "danger")
        return redirect(url_for('image.list_images'))
    
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
    return redirect(url_for('image.image_detail', image_id=image_id))

@image_routes.route('/tag_all', methods=['POST'])
def tag_all_images():
    """Déclenche le tagging de toutes les images non taguées"""
    # ...existing code...
    return redirect(url_for('image.list_images'))