from flask import Flask, request, jsonify
import logging
import docker
import os
import time
import json
import uuid

logger = logging.getLogger('orchestrator.api')

# Global variables
docker_client = None
app = None

def init_app(flask_app):
    """Initialize the Flask app with API routes"""
    global app, docker_client
    app = flask_app
    
    try:
        docker_client = docker.from_env()
        logger.info("Docker client initialized in API module")
    except Exception as e:
        logger.error(f"Failed to initialize Docker client in API: {e}")
    
    # Register routes
    register_routes(app)
    
    return app

def register_routes(app):
    """Register all API routes"""
    
    @app.route('/api/healthcheck', methods=['GET'])
    def healthcheck():
        """Simple health check endpoint"""
        return jsonify({
            "status": "ok",
            "timestamp": time.time(),
            "docker_connected": docker_client is not None
        })
    
    @app.route('/api/container/info', methods=['POST'])
    def get_container_info():
        """Get information about a specific container"""
        data = request.json
        service_name = data.get('service_name')
        worker_id = data.get('worker_id')
        
        if not service_name or not worker_id:
            return jsonify({"success": False, "message": "Missing service_name or worker_id"}), 400
        
        try:
            # Look for container with appropriate labels or environment variables
            containers = docker_client.containers.list(all=True)
            for container in containers:
                env = container.attrs.get('Config', {}).get('Env', [])
                for e in env:
                    if e == f"WORKER_ID={worker_id}" and service_name in container.name:
                        container_info = {
                            "id": container.id[:12],
                            "name": container.name,
                            "status": container.status
                        }
                        return jsonify({"success": True, "container_info": container_info})
            
            return jsonify({"success": False, "message": "Container not found"}), 404
        except Exception as e:
            logger.error(f"Error getting container info: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/container/logs', methods=['POST'])
    def get_container_logs():
        """Get logs from a specific container"""
        data = request.json
        service_name = data.get('service_name')
        worker_id = data.get('worker_id')
        lines = data.get('lines', 100)
        
        if not service_name or not worker_id:
            return jsonify({"success": False, "message": "Missing service_name or worker_id"}), 400
        
        try:
            # Look for container with appropriate labels or environment variables
            containers = docker_client.containers.list(all=True)
            for container in containers:
                env = container.attrs.get('Config', {}).get('Env', [])
                for e in env:
                    if e == f"WORKER_ID={worker_id}" and service_name in container.name:
                        logs = container.logs(tail=lines).decode('utf-8', errors='replace')
                        return jsonify({"success": True, "logs": logs})
            
            return jsonify({"success": False, "message": "Container not found"}), 404
        except Exception as e:
            logger.error(f"Error getting container logs: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/service/scale', methods=['POST'])
    def scale_service():
        """Scale a service to a specified number of replicas"""
        data = request.json
        service_name = data.get('service_name')
        count = int(data.get('count', 1))
        
        if not service_name or count < 1:
            return jsonify({"success": False, "message": "Missing service_name or invalid count"}), 400
        
        try:
            # Utiliser directement le client Docker au lieu de docker-compose
            logger.info(f"Scaling service {service_name} to {count} instances using Docker API")
            
            # Stratégie: Compter les conteneurs actuels, puis créer/supprimer selon besoin
            current_containers = docker_client.containers.list(
                all=True,
                filters={"label": [f"com.docker.compose.service={service_name}"]}
            )
            
            # Trouver les conteneurs en cours d'exécution et leur worker_id
            running_containers = []
            worker_ids = set()
            
            for container in current_containers:
                env_vars = container.attrs.get('Config', {}).get('Env', [])
                worker_id = None
                
                for env in env_vars:
                    if env.startswith("WORKER_ID="):
                        worker_id = int(env.split("=")[1])
                        worker_ids.add(worker_id)
                        break
                
                if worker_id is not None and container.status == "running":
                    running_containers.append((container, worker_id))
            
            current_count = len(running_containers)
            logger.info(f"Found {current_count} running containers for service {service_name}")
            
            # Si nous avons déjà le bon nombre, rien à faire
            if current_count == count:
                return jsonify({
                    "success": True,
                    "message": f"Service {service_name} already at {count} instances"
                })
            
            # Si nous devons augmenter le nombre
            if current_count < count:
                # Trouver l'image à utiliser en se basant sur les conteneurs existants
                image_name = None
                if current_containers:
                    image_name = current_containers[0].image.tags[0] if current_containers[0].image.tags else current_containers[0].image.id
                else:
                    # Chercher l'image par le nom du service
                    images = docker_client.images.list()
                    for image in images:
                        if not image.tags:
                            continue
                        for tag in image.tags:
                            if service_name in tag:
                                image_name = tag
                                break
                        if image_name:
                            break
                
                if not image_name:
                    return jsonify({
                        "success": False, 
                        "message": f"Cannot find image for service {service_name}"
                    }), 500
                
                # Trouver le prochain ID de worker disponible
                next_worker_id = 1
                while next_worker_id in worker_ids and next_worker_id <= count:
                    next_worker_id += 1
                
                # Créer les conteneurs manquants
                for i in range(current_count, count):
                    worker_id = next_worker_id
                    next_worker_id += 1
                    
                    container_name = f"{service_name}_{worker_id}"
                    
                    # Variables d'environnement
                    env_vars = {
                        "WORKER_ID": str(worker_id),
                        "DATABASE_URL": "mongodb://database:27017/imagesdb"
                    }
                    
                    # Créer le conteneur
                    try:
                        logger.info(f"Creating container {container_name} with image {image_name}")
                        new_container = docker_client.containers.run(
                            image_name,
                            detach=True,
                            name=container_name,
                            environment=env_vars,
                            network="partie2_app_network",
                            volumes={
                                "partie2_shared_data": {"bind": "/data", "mode": "rw"}
                            },
                            labels={
                                "com.docker.compose.project": "partie2",
                                "com.docker.compose.service": service_name
                            }
                        )
                        logger.info(f"Container {container_name} created successfully")
                    except Exception as e:
                        logger.error(f"Error creating container {container_name}: {e}")
                        return jsonify({
                            "success": False,
                            "message": f"Error creating containers: {str(e)}"
                        }), 500
                
                return jsonify({
                    "success": True,
                    "message": f"Service {service_name} scaled up to {count} instances"
                })
            
            # Si nous devons diminuer le nombre
            else:
                # Trier les conteneurs par worker_id décroissant pour supprimer les plus récents
                running_containers.sort(key=lambda x: x[1], reverse=True)
                
                # Supprimer les conteneurs en trop
                for container, worker_id in running_containers[:current_count - count]:
                    try:
                        logger.info(f"Removing container {container.name}")
                        container.remove(force=True)
                        logger.info(f"Container {container.name} removed successfully")
                    except Exception as e:
                        logger.error(f"Error removing container {container.name}: {e}")
                        return jsonify({
                            "success": False,
                            "message": f"Error scaling down: {str(e)}"
                        }), 500
                
                return jsonify({
                    "success": True,
                    "message": f"Service {service_name} scaled down to {count} instances"
                })
                
        except Exception as e:
            logger.error(f"Error scaling service: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/system/cleanup', methods=['POST'])
    def system_cleanup():
        """Nettoie complètement le système (workers, images, fichiers)"""
        try:
            # 1. Arrêter et supprimer tous les conteneurs des workers
            services_to_clean = ['image_downloader', 'image_tagger']
            cleaned_containers = 0
            
            for service_name in services_to_clean:
                containers = docker_client.containers.list(
                    all=True,
                    filters={"label": [f"com.docker.compose.service={service_name}"]}
                )
                
                logger.info(f"Nettoyage des conteneurs pour {service_name}: {len(containers)} trouvés")
                
                for container in containers:
                    try:
                        logger.info(f"Suppression du conteneur {container.name}")
                        container.remove(force=True)
                        cleaned_containers += 1
                    except Exception as e:
                        logger.error(f"Erreur lors de la suppression de {container.name}: {e}")
            
            # 2. Nettoyer les fichiers image du volume partagé
            try:
                logger.info("Tentative de nettoyage des fichiers images")
                import glob
                image_files = glob.glob("/data/images/*.jpg")
                file_count = len(image_files)
                
                for file in image_files:
                    os.remove(file)
                
                logger.info(f"{file_count} fichiers images supprimés")
            except Exception as e:
                logger.error(f"Erreur lors du nettoyage des fichiers: {e}")
                return jsonify({
                    "success": False,
                    "message": f"Conteneurs nettoyés, mais erreur fichiers: {str(e)}",
                    "containers_cleaned": cleaned_containers
                })
            
            return jsonify({
                "success": True,
                "message": f"Système nettoyé: {cleaned_containers} conteneurs et {file_count} fichiers supprimés"
            })
            
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage du système: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route('/api/task/redistribute', methods=['POST'])
    def redistribute_task():
        """Redistribute a task to another worker"""
        # Task redistribution implementation
        return jsonify({"success": True, "message": "Task redistributed"})

    # Add more routes as needed
