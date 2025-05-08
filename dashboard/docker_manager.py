import os
import docker
import logging
from time import sleep

# Configuration du logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('docker_manager')

class DockerScaler:
    """Classe pour gérer le scaling des conteneurs Docker"""
    
    def __init__(self, service_name="image_downloader", project_name="partie2"):
        """Initialisation avec le client Docker"""
        try:
            # Connexion au daemon Docker - utilise les variables d'environnement par défaut
            # ou le socket par défaut sur Unix/Windows
            self.client = docker.from_env()
            self.api_client = docker.APIClient()
            self.service_name = service_name
            self.project_name = project_name
            logger.info("Connexion au démon Docker établie")
        except Exception as e:
            logger.error(f"Erreur de connexion au démon Docker: {e}")
            self.client = None
            self.api_client = None
    
    def is_connected(self):
        """Vérifie si la connexion à Docker est établie"""
        return self.client is not None
    
    def get_current_scale(self):
        """Obtient le nombre actuel de conteneurs pour le service"""
        try:
            if not self.is_connected():
                return 0
                
            containers = self.client.containers.list(
                filters={
                    "label": [
                        f"com.docker.compose.project={self.project_name}",
                        f"com.docker.compose.service={self.service_name}"
                    ]
                }
            )
            return len(containers)
        except Exception as e:
            logger.error(f"Erreur lors de l'obtention du scaling actuel: {e}")
            return 0
    
    def scale_service(self, count):
        """Change le nombre de réplicas pour le service"""
        try:
            if not self.is_connected():
                logger.error("Impossible de scaler le service: non connecté au démon Docker")
                return False
            
            current_scale = self.get_current_scale()
            if current_scale == count:
                logger.info(f"Le service {self.service_name} est déjà scaled à {count}")
                return True
                
            logger.info(f"Scaling du service {self.service_name} de {current_scale} à {count}")
            
            # Utilisation de docker-compose scale via l'API Docker
            # Cette commande doit être exécutée dans le même répertoire que docker-compose.yml
            import subprocess
            try:
                cmd = f"docker-compose -p {self.project_name} up -d --scale {self.service_name}={count} {self.service_name}"
                logger.info(f"Exécution de la commande: {cmd}")
                result = subprocess.run(cmd, shell=True, check=True, capture_output=True)
                logger.info(f"Résultat du scaling: {result.stdout.decode()}")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Erreur lors du scaling: {e.stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Erreur lors du scaling du service: {e}")
            return False
    
    def calculate_optimal_workers(self, image_count):
        """Calcule le nombre optimal de workers basé sur le nombre d'images"""
        # Règle simple: 1 worker pour 20 images, minimum 2, maximum 6
        workers = max(2, min(6, (image_count // 20) + 1))
        logger.info(f"Nombre optimal de workers pour {image_count} images: {workers}")
        return workers

# Test unitaire simple
if __name__ == "__main__":
    scaler = DockerScaler()
    print(f"Connected: {scaler.is_connected()}")
    print(f"Current scale: {scaler.get_current_scale()}")
    
    # Test de la fonction de calcul
    for images in [10, 30, 50, 100, 150]:
        workers = scaler.calculate_optimal_workers(images)
        print(f"{images} images -> {workers} workers")
