import pymongo
import time
import logging
import os
import traceback
from pymongo.errors import ServerSelectionTimeoutError, AutoReconnect

logger = logging.getLogger('db_connector')

class RobustMongoClient:
    """Client MongoDB avec mécanisme de reconnexion automatique"""
    
    def __init__(self, uri=None, max_retries=10, retry_delay=2):
        self.uri = uri or os.environ.get('DATABASE_URL', 'mongodb://database:27017/imagesdb')
        self.client = None
        self.db = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.connect()
    
    def connect(self):
        """Établit une connexion à MongoDB avec mécanisme de retry"""
        retry_count = 0
        last_exception = None
        
        while retry_count < self.max_retries:
            try:
                # Tentative de connexion avec des paramètres robustes
                self.client = pymongo.MongoClient(
                    self.uri, 
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=10000,
                    retryWrites=True,
                    retryReads=True,
                    maxIdleTimeMS=45000
                )
                
                # Vérifier explicitement la connexion
                self.client.admin.command('ping')
                self.db = self.client.get_database()
                logger.info("✅ Connexion à MongoDB établie avec succès")
                return self.db
            except Exception as e:
                last_exception = e
                retry_count += 1
                
                # Calcul du délai avec backoff exponentiel
                delay = self.retry_delay * (2 ** (retry_count - 1))
                delay = min(delay, 30)  # Maximum 30 secondes de délai
                
                logger.warning(f"⚠️ Tentative de connexion {retry_count}/{self.max_retries} échouée: {str(e)}")
                logger.info(f"Nouvelle tentative dans {delay} secondes...")
                
                # Attendre avant de réessayer
                time.sleep(delay)
        
        logger.error(f"❌ Impossible de se connecter à MongoDB après {self.max_retries} tentatives: {last_exception}")
        # En dernier recours, on renvoie quand même un client, car les opérations futures tenteront de se reconnecter
        return self.client

    def execute_with_retry(self, operation, collection_name=None, default_value=None):
        """Exécute une opération MongoDB avec mécanisme de reconnexion automatique"""
        retry_count = 0
        
        while retry_count < self.max_retries:
            try:
                # Obtenir la collection si spécifiée
                if collection_name:
                    collection = self.db[collection_name]
                    return operation(collection)
                else:
                    return operation()
                    
            except (ServerSelectionTimeoutError, AutoReconnect) as e:
                retry_count += 1
                logger.warning(f"⚠️ Erreur de connexion (tentative {retry_count}/{self.max_retries}): {e}")
                
                if retry_count >= self.max_retries:
                    logger.error(f"❌ Échec après {self.max_retries} tentatives: {traceback.format_exc()}")
                    return default_value
                
                # Tenter de reconnecter avant le prochain essai
                try:
                    time.sleep(self.retry_delay)
                    self.connect()
                except Exception as reconnect_e:
                    logger.error(f"❌ Échec de reconnexion: {reconnect_e}")
            
            except Exception as e:
                logger.error(f"❌ Erreur inattendue: {e}")
                return default_value
        
        return default_value

# Instance singleton
_mongo_client = None

def get_database():
    """Renvoie l'instance singleton du client MongoDB robuste"""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = RobustMongoClient()
    return _mongo_client
