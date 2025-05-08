# Guide de vérification du système

Ce document explique comment vérifier que tous les composants du système fonctionnent correctement.

## 1. Vérifier le démarrage des conteneurs

Après avoir lancé le système avec `docker-compose up`, vérifiez que tous les conteneurs sont en cours d'exécution :

```bash
docker-compose ps
```

Tous les services devraient afficher l'état "Up" dans la colonne "State".

## 2. Consulter les logs des différents services

### Logs de tous les services
```bash
docker-compose logs
```

### Logs d'un service spécifique
```bash
docker-compose logs orchestrator
docker-compose logs image_downloader_1
docker-compose logs image_tagger_1
docker-compose logs recommendation
docker-compose logs database
```

Recherchez les messages d'erreur ou d'avertissement dans les logs.

## 3. Vérifier la base de données MongoDB

Connectez-vous à la base de données MongoDB :
```bash
docker exec -it partie2_database_1 mongo
```

Une fois dans l'interface MongoDB, vérifiez les collections :
```
use imagesdb
show collections
```

Vous devriez voir les collections suivantes :
- `images` (images téléchargées)
- `tags` (tags générés)
- `download_tasks` (tâches de téléchargement)
- `tagging_tasks` (tâches de tagging)
- `recommendation_tasks` (tâches de recommandation)
- `users` (utilisateurs du système)
- `user_likes` (préférences des utilisateurs)
- `recommendations` (recommandations générées)

Vérifiez le contenu de chaque collection :
```
db.images.find().limit(3)
db.tags.find().limit(3)
db.download_tasks.find()
db.tagging_tasks.find()
db.recommendation_tasks.find()
```

## 4. Vérifier les volumes partagés

Connectez-vous à un conteneur et examinez le contenu du volume partagé :
```bash
docker exec -it partie2_orchestrator_1 /bin/bash
ls -la /data/images
```

Vous devriez voir les images téléchargées dans ce répertoire.

## 5. Tester chaque composant individuellement

### Orchestrateur
Vérifiez dans les logs de l'orchestrateur s'il distribue correctement les tâches :
```bash
docker-compose logs orchestrator | grep "Tâches de téléchargement distribuées"
docker-compose logs orchestrator | grep "Tâches de tagging distribuées"
```

### Image Downloader
Vérifiez si les téléchargeurs d'images fonctionnent :
```bash
docker-compose logs image_downloader_1 | grep "Image téléchargée"
docker-compose logs image_downloader_2 | grep "Image téléchargée"
```

### Image Tagger
Vérifiez si les taggers d'images fonctionnent :
```bash
docker-compose logs image_tagger_1 | grep "Image taguée"
docker-compose logs image_tagger_2 | grep "Image taguée"
```

### Recommandation
Vérifiez si le système de recommandation fonctionne :
```bash
docker-compose logs recommendation | grep "Génération de recommandations"
```

## 6. Vérifier le flux de travail complet

Pour vérifier que le flux de travail complet fonctionne correctement, consultez MongoDB :
```bash
docker exec -it partie2_database_1 mongo
```

Dans l'interface MongoDB :
```
use imagesdb
db.images.count({ tagged: true })  # Nombre d'images taguées
db.recommendations.count()         # Nombre de recommandations générées
```

## 7. Problèmes courants et solutions

### Les conteneurs s'arrêtent immédiatement
- Vérifiez les logs pour identifier l'erreur :
  ```bash
  docker-compose logs [service]
  ```

### Problèmes de connexion à MongoDB
- Vérifiez que MongoDB est accessible :
  ```bash
  docker exec -it partie2_image_downloader_1_1 ping database
  ```

### Volumes non accessibles
- Vérifiez les permissions :
  ```bash
  docker-compose down -v
  docker-compose up
  ```

### Pas d'images téléchargées
- Vérifiez les logs du downloader et assurez-vous qu'il reçoit des tâches de l'orchestrateur
- Vérifiez que les URLs sont valides

### Pas de tags générés
- Assurez-vous que les images sont correctement téléchargées avant le tagging
- Vérifiez si OpenCV est correctement installé

### Pas de recommandations générées
- Vérifiez qu'il y a suffisamment d'images taguées
- Vérifiez s'il y a des utilisateurs dans la base de données

## 8. Résoudre le problème "JAVA_HOME is not set" pour PySpark

Si vous rencontrez l'erreur `JAVA_HOME is not set` et `Java gateway process exited before sending its port number`, c'est parce que PySpark nécessite Java pour fonctionner.

### Solution : Mettre à jour les Dockerfiles

Pour chaque service utilisant PySpark (orchestrator, image_downloader, image_tagger, recommendation), modifiez le Dockerfile comme suit :

1. Créez ou modifiez le fichier `Dockerfile` dans chaque dossier de service :

```dockerfile
FROM python:3.8-slim

# Installer Java
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    default-jdk \
    && rm -rf /var/lib/apt/lists/*

# Définir JAVA_HOME
ENV JAVA_HOME /usr/lib/jvm/java-11-openjdk-amd64
ENV PATH $JAVA_HOME/bin:$PATH

WORKDIR /app

# Installer les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Créer le répertoire pour stocker les images (uniquement pour image_downloader)
RUN mkdir -p /data/images

# Exécuter le service
CMD ["python", "service_script.py"]
```

Remplacez `service_script.py` par le nom de script approprié pour chaque service :
- `orchestrator.py` pour le service orchestrator
- `downloader.py` pour le service image_downloader
- `tagger.py` pour le service image_tagger
- `recommender.py` pour le service recommendation

2. Reconstruisez vos images Docker :

```bash
docker-compose down
docker-compose build --no-cache
docker-compose up
```

### Alternative : Utiliser des approches plus légères sans PySpark

Si vous n'avez pas besoin de toutes les fonctionnalités de PySpark, vous pouvez utiliser des alternatives plus légères :

1. **Pour le traitement parallèle** : Utilisez la bibliothèque `multiprocessing` de Python
2. **Pour map-reduce** : Utilisez `concurrent.futures` avec `map`
3. **Pour les expressions lambda** : Elles fonctionnent nativement en Python

Exemple de modification (pour orchestrator.py) :

```python
# Au lieu de PySpark RDD
# image_ids_rdd = spark.sparkContext.parallelize(image_ids)
# results = image_ids_rdd.map(tag_image).collect()

# Utilisez multiprocessing
from multiprocessing import Pool

with Pool(processes=4) as pool:
    results = pool.map(tag_image, image_ids)
```

### Vérifier le bon fonctionnement

Après avoir appliqué les modifications, vérifiez les logs pour vous assurer que les services démarrent correctement :

```bash
docker-compose logs orchestrator
docker-compose logs image_downloader_1
```

Vous ne devriez plus voir l'erreur "JAVA_HOME is not set".
