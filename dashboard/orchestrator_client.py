import requests
import json
import logging
import os
import socket
import docker
import time
import subprocess

logger = logging.getLogger('orchestrator_client')

class OrchestratorClient:
    """Client pour communiquer avec l'API de l'orchestrateur avec fallback en mode direct"""
    
    def __init__(self, api_url="http://orchestrator:5001/api"):
        self.api_url = api_url
        self.fallback_mode = False
        self.docker_client = None
        
        # Tester la connexion à l'API
        self.check_api_connection()

    def check_api_connection(self):
        """Vérifie si l'API de l'orchestrateur est accessible"""
        try:
            # Tenter une requête simple
            requests.get(f"{self.api_url}/healthcheck", timeout=2)
            self.fallback_mode = False
            logger.info("Connexion à l'API orchestrateur établie")
            return True
        except:
            # Basculer en mode de secours (fallback)
            logger.warning("Impossible de se connecter à l'API orchestrateur - passage en mode de secours direct")
            self.fallback_mode = True
            
            # Initialiser le client Docker pour le mode de secours
            try:
                self.docker_client = docker.from_env()
                logger.info("Client Docker initialisé pour le mode de secours")
                return False
            except Exception as e:
                logger.error(f"Impossible d'initialiser le client Docker: {e}")
                return False
    
    def create_container(self, service_name, worker_id):
        """Crée un conteneur via l'orchestrateur ou directement"""
        # Essayer d'abord l'API
        if not self.fallback_mode:
            try:
                response = requests.post(
                    f"{self.api_url}/container/create",
                    json={"service_name": service_name, "worker_id": worker_id},
                    timeout=30
                )
                
                if response.status_code == 200 and response.json().get("success"):
                    return True, response.json().get("message", "Conteneur créé avec succès")
                else:
                    error_msg = response.json().get("message", "Erreur inconnue")
                    # Si erreur avec l'API, essayer le mode de secours
                    self.fallback_mode = True
            except:
                # Passer en mode de secours
                self.fallback_mode = True
        
        # Mode de secours: utiliser Docker directement
        if self.fallback_mode:
            return self._direct_create_container(service_name, worker_id)
    
    def restart_container(self, service_name, worker_id):
        """Redémarre un conteneur via l'orchestrateur ou directement"""
        # Essayer d'abord l'API
        if not self.fallback_mode:
            try:
                response = requests.post(
                    f"{self.api_url}/container/restart",
                    json={"service_name": service_name, "worker_id": worker_id},
                    timeout=30
                )
                
                if response.status_code == 200 and response.json().get("success"):
                    return True, response.json().get("message", "Conteneur redémarré avec succès")
                else:
                    error_msg = response.json().get("message", "Erreur inconnue")
                    # Si erreur avec l'API, essayer le mode de secours
                    self.fallback_mode = True
            except:
                # Passer en mode de secours
                self.fallback_mode = True
        
        # Mode de secours: utiliser Docker directement
        if self.fallback_mode:
            return self._direct_restart_container(service_name, worker_id)
    
    def scale_service(self, service_name, count):
        """Fait scale un service via l'orchestrateur"""
        try:
            response = requests.post(
                f"{self.api_url}/service/scale",
                json={"service_name": service_name, "count": count},
                timeout=60  # Scaling peut prendre plus de temps
            )
            
            if response.status_code == 200 and response.json().get("success"):
                return True, response.json().get("message", "Service mis à l'échelle avec succès")
            else:
                error_msg = response.json().get("message", "Erreur inconnue")
                return False, error_msg
        except requests.RequestException as e:
            logger.error(f"Erreur de communication avec l'orchestrateur: {e}")
            return False, f"Erreur de connexion: {str(e)}"
    
    def redistribute_task(self, task_id):
        """Réassigne une tâche via l'orchestrateur"""
        try:
            response = requests.post(
                f"{self.api_url}/task/redistribute",
                json={"task_id": task_id},
                timeout=30
            )
            
            if response.status_code == 200 and response.json().get("success"):
                return True, response.json().get("message", "Tâche réassignée avec succès")
            else:
                error_msg = response.json().get("message", "Erreur inconnue")
                return False, error_msg
        except requests.RequestException as e:
            logger.error(f"Erreur de communication avec l'orchestrateur: {e}")
            return False, f"Erreur de connexion: {str(e)}"
    
    def get_container_logs(self, service_name, worker_id, lines=100):
        """Récupère les logs d'un conteneur via l'orchestrateur"""
        try:
            response = requests.post(
                f"{self.api_url}/container/logs",
                json={"service_name": service_name, "worker_id": worker_id, "lines": lines},
                timeout=30
            )
            
            if response.status_code == 200 and response.json().get("success"):
                return response.json().get("logs", "")
            else:
                return f"Erreur: {response.json().get('message', 'Erreur inconnue')}"
        except requests.RequestException as e:
            logger.error(f"Erreur de communication avec l'orchestrateur: {e}")
            return f"Erreur de connexion: {str(e)}"
    
    def _direct_create_container(self, service_name, worker_id):
        """Crée un conteneur directement avec le client Docker"""
        try:
            if not self.docker_client:
                self.docker_client = docker.from_env()
            
            # Vérifier si un conteneur existe déjà
            container_name = f"{service_name}_{worker_id}"
            try:
                container = self.docker_client.containers.get(container_name)
                if container.status == "running":
                    return True, f"Le conteneur {container_name} existe déjà et est en cours d'exécution"
                else:
                    # Supprimer l'ancien conteneur
                    container.remove(force=True)
            except docker.errors.NotFound:
                pass  # Le conteneur n'existe pas, c'est normal
            
            # Trouver une image appropriée
            image_name = None
            containers = self.docker_client.containers.list(
                all=True,
                filters={"label": [f"com.docker.compose.service={service_name}"]}
            )
            
            if containers:
                # Utiliser l'image du premier conteneur trouvé
                image_name = containers[0].image.id
                logger.info(f"Utilisation de l'image {image_name} basée sur un conteneur existant")
            else:
                # Essayer de trouver l'image par son nom
                project_name = "partie2"
                image_name = f"{project_name}_{service_name}"
                logger.info(f"Recherche de l'image {image_name}")
            
            # Variables d'environnement
            env_vars = {
                "WORKER_ID": str(worker_id),
                "DATABASE_URL": "mongodb://database:27017/imagesdb"
            }
            
            # Créer le conteneur
            try:
                new_container = self.docker_client.containers.run(
                    image_name,
                    detach=True,
                    name=container_name,
                    environment=env_vars,
                    network="partie2_app_network",
                    volumes={
                        "partie2_shared_data": {"bind": "/data", "mode": "rw"}
                    }
                )
                return True, f"Conteneur {container_name} créé avec succès (mode direct)"
            except docker.errors.ImageNotFound:
                return False, f"Image {image_name} introuvable"
            except Exception as e:
                return False, f"Erreur lors de la création du conteneur: {str(e)}"
            
        except Exception as e:
            return False, f"Erreur Docker lors de la création du conteneur: {str(e)}"
            
    def _direct_restart_container(self, service_name, worker_id):
        """Redémarre un conteneur directement avec le client Docker"""
        try:
            if not self.docker_client:
                self.docker_client = docker.from_env()
            
            # Essayer d'abord par le nom exact
            container_name = f"{service_name}_{worker_id}"
            try:
                container = self.docker_client.containers.get(container_name)
                container.restart()
                return True, f"Conteneur {container_name} redémarré avec succès (mode direct)"
            except docker.errors.NotFound:
                # Rechercher par les labels et variables d'environnement
                containers = self.docker_client.containers.list(
                    all=True,
                    filters={"label": [f"com.docker.compose.service={service_name}"]}
                )
                
                for container in containers:
                    env_vars = container.attrs.get('Config', {}).get('Env', [])
                    for env in env_vars:
                        if env == f"WORKER_ID={worker_id}":
                            container.restart()
                            return True, f"Conteneur {container.name} redémarré avec succès (mode direct)"
                
                # Si on arrive ici, on n'a pas trouvé de conteneur
                return False, f"Conteneur pour {service_name} worker {worker_id} non trouvé"
                
        except Exception as e:
            return False, f"Erreur Docker lors du redémarrage: {str(e)}"
