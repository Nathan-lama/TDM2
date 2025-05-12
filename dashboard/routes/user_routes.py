import time  # Ajout de l'import manquant
import uuid
import datetime
from flask import render_template, request, redirect, url_for, flash
from app import app, db

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
    
    # Analyser automatiquement les préférences basées sur les likes
    if liked_images:
        # Extraire les tags et couleurs des images aimées
        all_tags = []
        all_colors = []
        
        for image in liked_images:
            if "tags" in image and image["tags"]:
                all_tags.extend(image["tags"])
            
            if "dominant_colors" in image:
                for color in image["dominant_colors"]:
                    if "name" in color:
                        all_colors.append(color["name"])
        
        # Identifier les préférences les plus fréquentes
        from collections import Counter
        
        tag_counter = Counter(all_tags)
        favorite_tags = [tag for tag, _ in tag_counter.most_common(5)]
        
        color_counter = Counter(all_colors)
        favorite_colors = [color for color, _ in color_counter.most_common(5)]
        
        # Mettre à jour les préférences de l'utilisateur
        if favorite_tags or favorite_colors:
            db.users.update_one(
                {"_id": user_id},
                {"$set": {
                    "preferences.genres": favorite_tags,
                    "preferences.colors": favorite_colors,
                    "preferences_updated_at": time.time()
                }}
            )
            
            # Recharger l'utilisateur avec les préférences mises à jour
            user = db.users.find_one({"_id": user_id})
    
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

@app.route('/create_user', methods=['GET', 'POST'])
def create_user():
    """Crée un nouvel utilisateur"""
    if request.method == 'POST':
        user_id = request.form.get('user_id') or str(uuid.uuid4())
        name = request.form.get('name')
        
        if not name:
            flash("Le nom est requis", "warning")
            return redirect(url_for('create_user'))
        
        # Créer l'utilisateur avec des préférences vides qui seront déterminées automatiquement
        db.users.insert_one({
            "_id": user_id,
            "name": name,
            "preferences": {
                "genres": [],  # Sera rempli automatiquement
                "colors": []   # Sera rempli automatiquement
            },
            "created_at": datetime.datetime.now()
        })
        
        flash(f"Utilisateur {name} créé avec succès. Commencez à aimer des images pour générer des préférences!", "success")
        
        # Rediriger vers la navigation d'images pour commencer à générer des préférences
        return redirect(url_for('image_browser', user_id=user_id))
    
    return render_template('create_user.html')

@app.route('/like_image', methods=['POST'])
def like_image():
    """Ajoute un like/dislike à une image et déclenche des recommandations si nécessaire"""
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
    
    # Vérifier si l'utilisateur a au moins 5 likes pour déclencher des recommandations
    if liked:
        like_count = db.user_likes.count_documents({"user_id": user_id, "liked": True})
        
        if like_count >= 5:
            # Vérifier s'il existe déjà une tâche de recommandation récente
            recent_task = db.recommendation_tasks.find_one({
                "user_ids": user_id,
                "created_at": {"$gt": time.time() - 3600}  # Pas de nouvelle tâche si < 1h
            })
            
            if not recent_task:
                # Créer une nouvelle tâche de recommandation pour cet utilisateur
                db.recommendation_tasks.insert_one({
                    "_id": str(uuid.uuid4()),
                    "user_ids": [user_id],
                    "status": "pending",
                    "created_at": time.time(),
                    "priority": "high"  # Pour traitement prioritaire
                })
                
                if like_count == 5:
                    flash("Vous avez liké 5 images ! Nous préparons des recommandations pour vous.", "info")
    
    flash(f"Image {'likée' if liked else 'dislikée'} avec succès", "success")
    
    # Rediriger vers la page précédente ou vers les détails de l'utilisateur
    redirect_url = request.form.get('redirect_url') or url_for('image_browser', user_id=user_id)
    return redirect(redirect_url)

@app.route('/image_browser')
def image_browser():
    """Interface de type Tinder pour parcourir les images"""
    user_id = request.args.get('user_id')
    
    if not user_id:
        # S'il n'y a pas d'ID utilisateur, rediriger vers la page de sélection d'utilisateur
        users = list(db.users.find())
        if not users:
            flash("Aucun utilisateur trouvé. Veuillez créer un utilisateur d'abord.", "warning")
            return redirect(url_for('create_user'))
        return render_template('select_user.html', users=users, action="browse")
    
    # Vérifier si l'utilisateur existe
    user = db.users.find_one({"_id": user_id})
    if not user:
        flash("Utilisateur non trouvé", "danger")
        return redirect(url_for('users'))
    
    # Récupérer les interactions de l'utilisateur
    likes = list(db.user_likes.find({"user_id": user_id, "liked": True}))
    likes_count = len(likes)
    
    # Récupérer les dislikes
    dislikes = list(db.user_likes.find({"user_id": user_id, "liked": False}))
    dislike_ids = [dislike["image_id"] for dislike in dislikes]
    
    # Vérifier si des recommandations sont disponibles (5+ likes)
    show_recommendations = False
    recommended_images = []
    
    if likes_count >= 5:
        # Vérifier si des recommandations existent
        recs = db.recommendations.find_one({"user_id": user_id})
        
        if recs and "recommendations" in recs and recs["recommendations"]:
            # Des recommandations existent
            recommendations = recs["recommendations"]
            show_recommendations = len(recommendations) > 0
            
            if show_recommendations:
                # Récupérer les détails des images recommandées
                for rec in recommendations[:5]:  # Limiter à 5 recommandations
                    image_id = rec.get("image_id")
                    image = db.images.find_one({"_id": image_id})
                    if image:
                        image["recommendation_score"] = rec.get("score", 0)
                        recommended_images.append(image)
        else:
            # Pas de recommandations, vérifier s'il y a une tâche en cours
            existing_task = db.recommendation_tasks.find_one({
                "user_ids": user_id,
                "status": {"$in": ["pending", "in_progress"]}
            })
            
            if not existing_task:
                # Créer une nouvelle tâche
                task_id = str(uuid.uuid4())
                db.recommendation_tasks.insert_one({
                    "_id": task_id,
                    "user_ids": [user_id],
                    "status": "pending",
                    "created_at": time.time(),
                    "priority": "normal",
                    "source": "auto_triggered" 
                })
                app.logger.info(f"Tâche de recommandation {task_id} créée pour {user_id}")
    
    # Trouver une image non vue à montrer à l'utilisateur
    seen_image_ids = [like["image_id"] for like in likes] + dislike_ids
    
    next_image = db.images.find_one({
        "_id": {"$nin": seen_image_ids},
        "tagged": True  # Uniquement des images taguées
    })
    
    # S'il n'y a plus d'images à voir, afficher un message
    if not next_image:
        flash("Vous avez parcouru toutes les images disponibles !", "info")
        return redirect(url_for('user_detail', user_id=user_id))
    
    return render_template('image_browser.html', 
                          user_id=user_id,
                          image=next_image,
                          likes_count=likes_count,
                          show_recommendations=show_recommendations,
                          recommended_images=recommended_images)

@app.route('/user/<user_id>/recommendations')
def user_recommendations(user_id):
    """Affiche les recommandations pour un utilisateur spécifique"""
    # Vérifier si l'utilisateur existe
    user = db.users.find_one({"_id": user_id})
    if not user:
        flash("Utilisateur non trouvé", "danger")
        return redirect(url_for('users'))
    
    # Récupérer les likes de l'utilisateur
    likes = list(db.user_likes.find({"user_id": user_id, "liked": True}))
    likes_count = len(likes)
    liked_image_ids = [like["image_id"] for like in likes]
    
    # Récupérer les recommandations existantes
    recommendations_doc = db.recommendations.find_one({"user_id": user_id})
    recommendations = []
    
    # Vérifier si des recommandations existent et si elles sont valides
    if recommendations_doc and "recommendations" in recommendations_doc:
        recs_list = recommendations_doc.get("recommendations", [])
        
        if recs_list:
            # Des recommandations existent, les récupérer
            for rec in recs_list:
                image_id = rec.get("image_id")
                score = rec.get("score", 0)
                
                # Trouver l'image
                image = db.images.find_one({"_id": image_id})
                if image:
                    image["recommendation_score"] = score
                    recommendations.append(image)
    
    # Si l'utilisateur a suffisamment de likes mais pas de recommandations, en créer
    if likes_count >= 5 and not recommendations:
        # Vérifier si une tâche est déjà en cours
        existing_task = db.recommendation_tasks.find_one({
            "user_ids": user_id,
            "status": {"$in": ["pending", "in_progress"]}
        })
        
        if not existing_task:
            # Créer une nouvelle tâche de recommandation avec priorité haute
            task_id = str(uuid.uuid4())
            db.recommendation_tasks.insert_one({
                "_id": task_id,
                "user_ids": [user_id],
                "status": "pending",
                "created_at": time.time(),
                "priority": "high",
                "source": "manual_request"
            })
            
            flash(f"Génération de nouvelles recommandations lancée. Veuillez réessayer dans quelques instants.", "info")
    
    # Statistiques pour l'affichage
    stats = {
        "total_recommendations": len(recommendations),
        "generated_at": recommendations_doc.get("generated_at", 0) if recommendations_doc else 0,
        "likes_count": likes_count
    }
    
    # Trier les recommandations par score
    recommendations.sort(key=lambda x: x.get("recommendation_score", 0), reverse=True)
    
    return render_template('user_recommendations.html', 
                          user=user,
                          recommendations=recommendations,
                          liked_image_ids=liked_image_ids,
                          stats=stats)

@app.route('/regenerate_recommendations', methods=['POST'])
def regenerate_recommendations():
    """Force la régénération des recommandations pour un utilisateur"""
    user_id = request.form.get('user_id')
    
    if not user_id:
        flash("ID utilisateur requis", "danger")
        return redirect(url_for('users'))
    
    # Supprimer les recommandations existantes
    db.recommendations.delete_one({"user_id": user_id})
    
    # Annuler toute tâche en cours pour cet utilisateur
    db.recommendation_tasks.update_many(
        {"user_ids": user_id, "status": {"$in": ["pending", "in_progress"]}},
        {"$set": {"status": "cancelled"}}
    )
    
    # Créer une nouvelle tâche prioritaire
    task_id = str(uuid.uuid4())
    db.recommendation_tasks.insert_one({
        "_id": task_id,
        "user_ids": [user_id],
        "status": "pending",
        "created_at": time.time(),
        "priority": "high",
        "source": "manual_regenerate"
    })
    
    flash("Génération de nouvelles recommandations lancée. Veuillez attendre quelques instants.", "success")
    return redirect(url_for('user_recommendations', user_id=user_id))
