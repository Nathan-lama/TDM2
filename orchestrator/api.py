from flask import Flask, request, jsonify
import autoscaler
import logging
import os

# Configuration du logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('orchestrator_api')

app = Flask(__name__)

@app.route('/api/container/create', methods=['POST'])
def create_container():
    """API pour créer un nouveau conteneur worker"""
    data = request.json
    if not data or 'service_name' not in data or 'worker_id' not in data:
        return jsonify({"success": False, "message": "Paramètres manquants"}), 400
    
    service_name = data['service_name']
    worker_id = int(data['worker_id'])
    
    if autoscaler.create_worker_container(service_name, worker_id):
        return jsonify({"success": True, "message": f"Conteneur {service_name}_{worker_id} créé avec succès"})
    else:
        return jsonify({"success": False, "message": f"Échec de la création du conteneur {service_name}_{worker_id}"}), 500

@app.route('/api/container/restart', methods=['POST'])
def restart_container():
    """API pour redémarrer un conteneur worker"""
    data = request.json
    if not data or 'service_name' not in data or 'worker_id' not in data:
        return jsonify({"success": False, "message": "Paramètres manquants"}), 400
    
    service_name = data['service_name']
    worker_id = int(data['worker_id'])
    
    if autoscaler.restart_worker_container(service_name, worker_id):
        return jsonify({"success": True, "message": f"Conteneur {service_name}_{worker_id} redémarré avec succès"})
    else:
        return jsonify({"success": False, "message": f"Échec du redémarrage du conteneur {service_name}_{worker_id}"}), 500

@app.route('/api/service/scale', methods=['POST'])
def scale_service():
    """API pour faire scale un service Docker"""
    data = request.json
    if not data or 'service_name' not in data or 'count' not in data:
        return jsonify({"success": False, "message": "Paramètres manquants"}), 400
    
    service_name = data['service_name']
    count = int(data['count'])
    
    if autoscaler.scale_service_via_compose(service_name, count):
        return jsonify({"success": True, "message": f"Service {service_name} mis à l'échelle à {count} instances"})
    else:
        return jsonify({"success": False, "message": f"Échec du scaling du service {service_name}"}), 500

@app.route('/api/task/redistribute', methods=['POST'])
def redistribute_task():
    """API pour réassigner une tâche à un autre worker"""
    data = request.json
    if not data or 'task_id' not in data:
        return jsonify({"success": False, "message": "ID de tâche manquant"}), 400
    
    task_id = data['task_id']
    
    if autoscaler.redistribute_task(task_id):
        return jsonify({"success": True, "message": f"Tâche {task_id} réassignée avec succès"})
    else:
        return jsonify({"success": False, "message": f"Échec de la réassignation de la tâche {task_id}"}), 500

@app.route('/api/container/logs', methods=['POST'])
def get_container_logs():
    """API pour récupérer les logs d'un conteneur"""
    data = request.json
    if not data or 'service_name' not in data or 'worker_id' not in data:
        return jsonify({"success": False, "message": "Paramètres manquants"}), 400
    
    service_name = data['service_name']
    worker_id = int(data['worker_id'])
    lines = int(data.get('lines', 100))
    
    logs = autoscaler.get_container_logs(service_name, worker_id, lines)
    return jsonify({"success": True, "logs": logs})

def start_api_server(host='0.0.0.0', port=5001, debug=False):
    """Démarre le serveur API de l'orchestrateur"""
    logger.info(f"Démarrage de l'API sur {host}:{port}")
    app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    start_api_server()
