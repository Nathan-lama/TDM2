from flask import render_template
from app import app, db

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
