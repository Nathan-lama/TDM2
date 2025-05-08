from config import app
import utils.template_filters
from flask import redirect, url_for, request, send_file, flash
import os

# Enregistrer les routes
from routes.main_routes import main_routes
from routes.image_routes import image_routes
from routes.user_routes import user_routes
from routes.task_routes import task_routes
from routes.worker_routes import worker_routes

# Enregistrer les blueprints
app.register_blueprint(main_routes)
app.register_blueprint(image_routes)
app.register_blueprint(user_routes)
app.register_blueprint(task_routes)
app.register_blueprint(worker_routes)

# Routes de redirection pour la rétrocompatibilité
@app.route('/images/<image_id>')
def direct_serve_image(image_id):
    """Route directe pour servir une image depuis le volume partagé"""
    image_path = f"/data/images/{image_id}.jpg"
    
    if not os.path.exists(image_path):
        return send_file("static/no-image.jpg", mimetype='image/jpeg')
    
    return send_file(image_path, mimetype='image/jpeg')

@app.route('/batch_download', methods=['GET', 'POST'])
def redirect_batch_download():
    """Redirect to the new batch_download route"""
    return redirect(url_for('task.batch_download'))

@app.route('/clear_database', methods=['GET', 'POST'])
def redirect_clear_database():
    """Redirect to the new clear_database route"""
    print("⚠️ REDIRECTION depuis /clear_database vers /tasks/clear_database")
    
    # Si c'est un POST, on redirige vers le traitement du blueprint
    if request.method == 'POST':
        flash("Redirection vers la fonction de nettoyage...", "info")
        return redirect(url_for('task.clear_database'), code=307)  # 307 maintient la méthode POST
    
    return redirect(url_for('task.clear_database'))

@app.route('/worker_debug')
def redirect_worker_debug():
    """Redirect to the new worker debug route"""
    return redirect(url_for('worker.worker_debug'))

@app.route('/create_task', methods=['GET', 'POST'])
def redirect_create_task():
    """Redirect to the new create_task route"""
    return redirect(url_for('task.create_task'))

@app.route('/task_debug/<task_id>')
def redirect_task_debug(task_id):
    """Redirect to the new task debug route"""
    return redirect(url_for('task.task_debug', task_id=task_id))

# Ajouter une redirection pour /images
@app.route('/images')
@app.route('/images/')
def redirect_images():
    """Redirect to the new images list route"""
    return redirect(url_for('image.list_images'))

# Additional redirects for container operations
@app.route('/create_container/<service_name>/<int:worker_id>', methods=['POST'])
def redirect_create_container(service_name, worker_id):
    """Redirect to the new create_container route"""
    return redirect(url_for('worker.create_container', service_name=service_name, worker_id=worker_id))

@app.route('/restart_container/<service_name>/<int:worker_id>', methods=['POST'])
def redirect_restart_container(service_name, worker_id):
    """Redirect to the new restart_container route"""
    return redirect(url_for('worker.restart_container', service_name=service_name, worker_id=worker_id))

@app.route('/redistribute_task/<task_id>', methods=['POST'])
def redirect_redistribute_task(task_id):
    """Redirect to the new redistribute_task route"""
    return redirect(url_for('task.redistribute_task', task_id=task_id))

# Rediriger tous les chemins de type /images/<image_id> vers la bonne route
@app.route('/images/<image_id>')
def serve_image_direct(image_id):
    """Sert directement une image sans passer par le blueprint"""
    image_path = f"/data/images/{image_id}.jpg"
    
    # Vérifier si l'image existe
    if not os.path.exists(image_path):
        # Retourner une image par défaut ou une erreur 404
        return send_file("static/no-image.jpg", mimetype='image/jpeg')
    
    # Servir l'image
    return send_file(image_path, mimetype='image/jpeg')

# Lancer l'application
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
