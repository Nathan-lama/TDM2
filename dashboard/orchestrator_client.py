<<<<<<< HEAD
=======
import requests
import json
import logging
import os
import socket
import docker
import time
import subprocess
import traceback

logger = logging.getLogger('orchestrator_client')

class OrchestratorClient:
    """Client pour communiquer avec l'API de l'orchestrateur avec fallback en mode direct"""
    
    def __init__(self, api_url=None):
        # Use environment variable if provided, otherwise use default
        self.api_url = api_url or os.environ.get('ORCHESTRATOR_API_URL', "http://orchestrator:5001/api")
        self.fallback_mode = False
        self.docker_client = None
        
        # Tester la connexion à l'API
        self.check_api_connection()

    def check_api_connection(self):
        """Vérifie si l'API de l'orchestrateur est accessible"""
        try:
            # Tenter une requête simple avec un court timeout
            logger.info(f"Tentative de connexion à {self.api_url}...")
            response = requests.get(f"{self.api_url}/healthcheck", timeout=1)
            
            if response.status_code == 200:
                self.fallback_mode = False
                logger.info("Connexion à l'API orchestrateur établie")
                return True
                
            logger.warning(f"L'API a répondu avec le code {response.status_code}")
            self.fallback_mode = True
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Impossible de se connecter à l'API orchestrateur: {e}")
            self.fallback_mode = True
        except requests.exceptions.Timeout:
            logger.warning("Délai d'attente dépassé lors de la connexion à l'API orchestrateur")
            self.fallback_mode = True
        except Exception as e:
            logger.warning(f"Erreur lors de la connexion à l'API orchestrateur: {e}")
            self.fallback_mode = True
            
        # Si on arrive ici, c'est qu'il y a eu une erreur - on passe en mode de secours
        logger.warning("Passage en mode de secours direct")
        
        # Initialiser le client Docker pour le mode de secours
        try:
            self.docker_client = docker.from_env()
            logger.info("Client Docker initialisé pour le mode de secours")
            return False
        except Exception as e:
            logger.error(f"Impossible d'initialiser le client Docker: {e}")
            return False
    
    def is_connected(self):
        """Vérifie si le client est connecté à l'API orchestrateur"""
        return not self.fallback_mode
    
    def get_current_scale(self):
        """Récupère l'échelle actuelle des workers"""
        if self.fallback_mode:
            try:
                if self.docker_client:
                    containers = self.docker_client.containers.list(
                        filters={"label": ["com.docker.compose.service=image_downloader"]}
                    )
                    return len(containers)
            except Exception as e:
                logger.error(f"Erreur lors de la récupération de l'échelle actuelle: {e}")
        return 2  # Valeur par défaut
    
    def get_container_info(self, service_name, worker_id):
        """Récupère des informations sur un conteneur"""
        if not self.fallback_mode:
            try:
                response = requests.post(
                    f"{self.api_url}/container/info",
                    json={"service_name": service_name, "worker_id": worker_id},
                    timeout=2
                )
                
                if response.status_code == 200 and response.json().get("success"):
                    return response.json().get("container_info")
            except:
                # Passer en mode de secours en cas d'erreur
                self.fallback_mode = True
        
        # Mode de secours
        if self.fallback_mode:
            try:
                if not self.docker_client:
                    self.docker_client = docker.from_env()
                    
                # Rechercher le conteneur par nom exact
                container_name = f"{service_name}_{worker_id}"
                try:
                    container = self.docker_client.containers.get(container_name)
                    return {
                        "id": container.id[:12],
                        "name": container.name,
                        "status": container.status
                    }
                except docker.errors.NotFound:
                    # Essayer de trouver par les variables d'environnement
                    containers = self.docker_client.containers.list(
                        all=True,
                        filters={"label": [f"com.docker.compose.service={service_name}"]}
                    )
                    
                    for container in containers:
                        env_vars = container.attrs.get('Config', {}).get('Env', [])
                        for env in env_vars:
                            if env == f"WORKER_ID={worker_id}":
                                return {
                                    "id": container.id[:12],
                                    "name": container.name,
                                    "status": container.status
                                }
            except Exception as e:
                logger.error(f"Erreur lors de la recherche du conteneur: {e}")
        
        return None
    
    def get_container_logs(self, service_name, worker_id, lines=100):
        """Récupère les logs d'un conteneur"""
        if not self.fallback_mode:
            try:
                response = requests.post(
                    f"{self.api_url}/container/logs",
                    json={"service_name": service_name, "worker_id": worker_id, "lines": lines},
                    timeout=5
                )
                
                if response.status_code == 200 and response.json().get("success"):
                    return response.json().get("logs", "")
                else:
                    # Passer en mode de secours si on ne peut pas récupérer les logs
                    self.fallback_mode = True
            except Exception as e:
                logger.error(f"Erreur lors de la récupération des logs via API: {e}")
                self.fallback_mode = True
        
        # Mode de secours
        if self.fallback_mode:
            try:
                if not self.docker_client:
                    self.docker_client = docker.from_env()
                
                container_info = self.get_container_info(service_name, worker_id)
                if container_info:
                    container = self.docker_client.containers.get(container_info["id"])
                    logs = container.logs(tail=lines).decode('utf-8', errors='replace')
                    return logs
                return "Conteneur non trouvé"
            except Exception as e:
                logger.error(f"Erreur lors de la récupération des logs en mode direct: {e}")
                return f"Erreur: {str(e)}"
    
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
            except Exception as e:
                logger.error(f"Erreur API lors de la création du conteneur: {e}")
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
        """Fait scale un service via l'orchestrateur avec fallback direct"""
        # Essayer d'abord via l'API
        if not self.fallback_mode:
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
                    logger.warning(f"Échec du scaling via API: {error_msg} - Passage en mode direct")
                    # Passage en mode fallback
                    self.fallback_mode = True
            except requests.RequestException as e:
                logger.error(f"Erreur de communication avec l'orchestrateur: {e}")
                logger.info("Passage en mode de secours direct pour le scaling")
                self.fallback_mode = True
        
        # Mode de secours direct
        return self._direct_scale_service(service_name, count)
    
    def _direct_scale_service(self, service_name, count):
        """Redimensionne un service directement via docker-compose up --scale"""
        try:
            cmd = f"docker-compose up -d --scale {service_name}={count}"
            logger.info(f"Exécution de la commande: {cmd}")
            
            result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if result.returncode == 0:
                logger.info(f"Service {service_name} mis à l'échelle avec succès à {count} instances")
                return True, f"Service {service_name} mis à l'échelle à {count} instances"
            else:
                error = result.stderr.decode()
                logger.error(f"Erreur lors du scaling: {error}")
                return False, f"Erreur lors du scaling: {error}"
                
        except Exception as e:
            error_msg = f"Erreur lors du scaling: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

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
    
    def _direct_create_container(self, service_name, worker_id):
        """Crée un conteneur directement avec le client Docker"""
        try:
            if not self.docker_client:
                self.docker_client = docker.from_env()
            
            # Vérifier si un conteneur existe déjà avec ce nom
            container_name = f"{service_name}_{worker_id}"
            try:
                # Rechercher par le nom exact
                existing_container = self.docker_client.containers.get(container_name)
                
                # Si le conteneur existe déjà, vérifier son état
                if existing_container.status == "running":
                    logger.info(f"Le conteneur {container_name} existe déjà et est en cours d'exécution")
                    return True, f"Le conteneur {container_name} existe déjà et est en cours d'exécution"
                else:
                    # Arrêter et supprimer le conteneur existant
                    logger.info(f"Suppression du conteneur existant {container_name} (statut: {existing_container.status})")
                    try:
                        existing_container.stop(timeout=1)
                    except:
                        pass  # Ignorer les erreurs d'arrêt
                    
                    try:
                        existing_container.remove(force=True)
                        logger.info(f"Conteneur {container_name} supprimé avec succès")
                    except Exception as remove_error:
                        logger.error(f"Erreur lors de la suppression du conteneur {container_name}: {remove_error}")
                        # Essayer une approche alternative en utilisant l'API Docker directement
                        try:
                            self.docker_client.api.remove_container(container_name, force=True)
                            logger.info(f"Conteneur {container_name} supprimé avec succès via API directe")
                        except Exception as api_error:
                            logger.error(f"Échec de la suppression via API aussi: {api_error}")
                            return False, f"Impossible de supprimer le conteneur existant: {str(remove_error)}"
            except docker.errors.NotFound:
                # Le conteneur n'existe pas, c'est normal
                pass
            
            # Trouver une image appropriée
            image_name = None
            
            # 1. Chercher dans les conteneurs existants du même service
            containers = self.docker_client.containers.list(
                all=True,
                filters={"label": [f"com.docker.compose.service={service_name}"]}
            )
            
            if containers:
                # Utiliser l'image du premier conteneur trouvé
                image_name = containers[0].image.tags[0] if containers[0].image.tags else containers[0].image.id
                logger.info(f"Utilisation de l'image {image_name} basée sur un conteneur existant")
            else:
                # 2. Essayer de trouver l'image par son nom
                project_name = "partie2"  # Nom par défaut du projet docker-compose
                possible_names = [
                    f"{service_name}",
                    f"{project_name}_{service_name}",
                    f"partie2-{service_name}",
                    f"{service_name.replace('image_', '')}",
                    f"{project_name}-{service_name}"
                ]
                
                # Lister toutes les images disponibles
                all_images = self.docker_client.images.list()
                
                for img in all_images:
                    if not img.tags:
                        continue
                    
                    for tag in img.tags:
                        for name in possible_names:
                            if name.lower() in tag.lower():
                                image_name = tag
                                logger.info(f"Image trouvée par nom: {image_name}")
                                break
                        if image_name:
                            break
                    if image_name:
                        break
            
            # Si aucune image trouvée, utiliser le nom du service comme dernier recours
            if not image_name:
                image_name = service_name
                logger.warning(f"Aucune image trouvée, utilisation du nom par défaut: {image_name}")
            
            # Variables d'environnement
            env_vars = {
                "WORKER_ID": str(worker_id),
                "DATABASE_URL": "mongodb://database:27017/imagesdb"
            }
            
            # Créer le conteneur avec une gestion des erreurs
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"Tentative {attempt+1}/{max_retries} de création du conteneur {container_name}")
                    
                    # Si c'est une nouvelle tentative, attendre un peu
                    if attempt > 0:
                        time.sleep(2)
                        
                        # Essayer de nettoyer tout conteneur existant avec ce nom
                        try:
                            self.docker_client.api.remove_container(container_name, force=True)
                            logger.info(f"Conteneur {container_name} supprimé avant nouvelle tentative")
                        except:
                            pass
                    
                    new_container = self.docker_client.containers.run(
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
                            "com.docker.compose.service": service_name,
                            "worker_id": str(worker_id)
                        }
                    )
                    return True, f"Conteneur {container_name} créé avec succès (mode direct). ID: {new_container.id[:12]}"
                except docker.errors.ImageNotFound:
                    return False, f"Image {image_name} introuvable"
                except docker.errors.APIError as api_error:
                    if "Conflict" in str(api_error) and attempt < max_retries - 1:
                        logger.warning(f"Conflit détecté, tentative de suppression du conteneur existant")
                        try:
                            self.docker_client.api.remove_container(container_name, force=True)
                            logger.info(f"Nettoyage réussi, nouvelle tentative...")
                            continue  # Essayer à nouveau
                        except:
                            logger.error("Échec du nettoyage")
                    logger.error(f"Erreur API Docker lors de la création: {api_error}")
                    if attempt == max_retries - 1:
                        return False, f"Erreur après {max_retries} tentatives: {str(api_error)}"
                except Exception as e:
                    logger.error(f"Erreur lors de la création du conteneur: {e}")
                    logger.error(traceback.format_exc())
                    if attempt == max_retries - 1:
                        return False, f"Erreur après {max_retries} tentatives: {str(e)}"
                
        except Exception as e:
            logger.error(f"Erreur Docker lors de la création du conteneur: {e}")
            logger.error(traceback.format_exc())
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
    
    def is_connected(self):
        """Vérifie si le client est connecté à l'orchestrateur"""
        return not self.fallback_mode
    
    def get_current_scale(self):
        """Obtient le nombre actuel de workers"""
        try:
            if self.fallback_mode and self.docker_client:
                containers = self.docker_client.containers.list(
                    filters={"label": ["com.docker.compose.service=image_downloader"]}
                )
                return len(containers)
            else:
                # Tenter via l'API de l'orchestrateur
                response = requests.get(f"{self.api_url}/service/scale/image_downloader", timeout=5)
                if response.status_code == 200:
                    return response.json().get("count", 2)
                return 2
        except:
            return 2  # Valeur par défaut

    def get_container_info(self, service_name, worker_id):
        """Get information about a specific container"""
        try:
            if self.docker_client:
                # Try to find container with worker_id
                containers = self.docker_client.containers.list(all=True)
                for container in containers:
                    env = container.attrs.get('Config', {}).get('Env', [])
                    for e in env:
                        if e == f"WORKER_ID={worker_id}" and service_name in container.name:
                            return {
                                "id": container.id[:12],
                                "name": container.name,
                                "status": container.status
                            }
            return None
        except Exception as e:
            return None
>>>>>>> 6225a782b678423ab828fcbe9e7157a490688534
