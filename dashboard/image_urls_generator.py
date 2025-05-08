"""
Script pour obtenir des images depuis Wikidata
"""
import requests
import logging

# Configuration du logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('image_generator')

def get_wikidata_images(query, count=20):
    """Récupère des images depuis Wikidata pour une requête donnée"""
    try:
        # URL de l'API Wikidata
        url = "https://www.wikidata.org/w/api.php"
        
        # Paramètres de recherche
        params = {
            "action": "wbsearchentities",
            "format": "json",
            "language": "fr",
            "type": "item",
            "limit": count,
            "search": query
        }
        
        # Exécution de la recherche
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Récupération des IDs d'entités
        entity_ids = []
        if 'search' in data:
            for item in data['search']:
                if 'id' in item:
                    entity_ids.append(item['id'])
        
        # Pour chaque entité, récupérer son image si disponible
        image_urls = []
        for entity_id in entity_ids:
            # Paramètres pour obtenir les détails de l'entité
            entity_params = {
                "action": "wbgetentities",
                "format": "json",
                "ids": entity_id,
                "props": "claims"
            }
            
            entity_response = requests.get(url, params=entity_params)
            entity_response.raise_for_status()
            entity_data = entity_response.json()
            
            # Extraction de l'image (propriété P18 dans Wikidata)
            if 'entities' in entity_data and entity_id in entity_data['entities']:
                entity = entity_data['entities'][entity_id]
                if 'claims' in entity and 'P18' in entity['claims']:
                    for claim in entity['claims']['P18']:
                        if 'mainsnak' in claim and 'datavalue' in claim['mainsnak']:
                            file_name = claim['mainsnak']['datavalue']['value']
                            # Construction de l'URL d'image Wikimedia Commons
                            file_name = file_name.replace(" ", "_")
                            # Génération du hachage MD5 pour l'URL de l'image
                            import hashlib
                            md5_hash = hashlib.md5(file_name.encode()).hexdigest()
                            # Construction de l'URL finale
                            image_url = f"https://upload.wikimedia.org/wikipedia/commons/{md5_hash[0]}/{md5_hash[0:2]}/{file_name}"
                            image_urls.append(image_url)
                            break
        
        logger.info(f"Récupéré {len(image_urls)} images depuis Wikidata pour la requête '{query}'")
        return image_urls
    
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des images Wikidata : {e}")
        return []

def get_themed_queries():
    """Retourne des requêtes thématiques pour Wikidata"""
    themes = {
        "nature": [
            "montagne", "forêt", "océan", "cascade", "paysage", "plage",
            "rivière", "volcan", "lac", "désert"
        ],
        "architecture": [
            "gratte-ciel", "château", "cathédrale", "pont", "tour", "monument",
            "temple", "église", "bâtiment historique", "musée"
        ],
        "animaux": [
            "lion", "éléphant", "tigre", "oiseau", "baleine", "cheval",
            "dauphin", "girafe", "panda", "loup"
        ],
        "technologie": [
            "ordinateur", "téléphone", "satellite", "robot", "fusée", "invention",
            "voiture", "avion", "smartphone", "drone"
        ]
    }
    return themes

def get_wikidata_themed_images(theme, count=50):
    """Obtient des images depuis Wikidata par thème"""
    themes = get_themed_queries()
    if (theme in themes):
        queries = themes[theme]
        all_images = []
        images_per_query = max(5, count // len(queries))
        
        for query in queries:
            images = get_wikidata_images(query, images_per_query)
            all_images.extend(images)
            if len(all_images) >= count:
                break
                
        return all_images[:count]
    else:
        return get_wikidata_images("paysage", count)  # Thème par défaut

def get_themed_urls(theme, count=50):
    """
    Fonction de compatibilité pour maintenir l'interface précédente
    Redirige vers get_wikidata_themed_images
    """
    logger.info(f"Redirection de get_themed_urls vers get_wikidata_themed_images pour {theme}")
    return get_wikidata_themed_images(theme, count)
