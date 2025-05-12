import os
import time
from flask import render_template, request, redirect, url_for, flash, send_file
from app import app, db

@app.route('/images-galery')
def images_gallery():
    """Affiche les images disponibles dans la galerie"""
    page = int(request.args.get('page', 1))
    per_page = 20
    skip = (page - 1) * per_page
    
    # Récupérer toutes les images sans filtres particuliers
    images = list(db.images.find().skip(skip).limit(per_page))
    total = db.images.count_documents({})
    
    # Ajouter des informations de débogage pour vérifier ce qui est récupéré
    app.logger.info(f"Images récupérées: {len(images)} sur un total de {total}")
    
    return render_template('images.html', 
                          images=images, 
                          page=page, 
                          total=total, 
                          per_page=per_page,
                          total_pages=(total // per_page) + (1 if total % per_page > 0 else 0))

# Conserver la route existante pour la retrocompatibilité
@app.route('/images')
def images():
    """Redirection vers la nouvelle route de galerie"""
    return redirect(url_for('images_gallery'))

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
    try:
        image_path = f"/data/images/{image_id}.jpg"
        
        # Vérifier si l'image existe
        if not os.path.exists(image_path):
            app.logger.warning(f"Image introuvable: {image_path}")
            # Retourner une image par défaut
            return send_file("static/no-image.jpg", mimetype='image/jpeg')
        
        # Servir l'image
        return send_file(image_path, mimetype='image/jpeg')
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération de l'image {image_id}: {str(e)}")
        return send_file("static/no-image.jpg", mimetype='image/jpeg')

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
        db.tagging_tasks.insert_one({
            "_id": f"manual_{image_id}_{int(time.time())}",
            "worker_id": worker_id,
            "image_ids": [image_id],
            "status": "pending",
            "created_at": time.time(),
            "priority": "high",
            "manual": True
        })
        
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
