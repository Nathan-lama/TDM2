from flask import Blueprint, render_template, request, redirect, url_for, flash
from config import db
import uuid
import datetime

user_routes = Blueprint('user', __name__, url_prefix='/users')

@user_routes.route('/')
def users():
    """Liste des utilisateurs"""
    users = list(db.users.find())
    return render_template('users.html', users=users)

@user_routes.route('/<user_id>')
def user_detail(user_id):
    """Détails d'un utilisateur et ses préférences"""
    user = db.users.find_one({"_id": user_id})
    if not user:
        flash("Utilisateur non trouvé", "danger")
        return redirect(url_for('user.users'))
    
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

@user_routes.route('/create', methods=['GET', 'POST'])
def create_user():
    """Crée un nouvel utilisateur"""
    if request.method == 'POST':
        user_id = request.form.get('user_id') or str(uuid.uuid4())
        name = request.form.get('name')
        
        if not name:
            flash("Le nom est requis", "warning")
            return redirect(url_for('user.create_user'))
        
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
        return redirect(url_for('user.users'))
    
    return render_template('create_user.html')

@user_routes.route('/like', methods=['POST'])
def like_image():
    """Ajoute un like/dislike à une image"""
    # ...existing code...

@user_routes.route('/browse')
def image_browser():
    """Interface de type Tinder pour parcourir les images"""
    # ...existing code...