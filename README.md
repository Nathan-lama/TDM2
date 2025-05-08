# Système de Recommandation d'Images - Partie 2

Ce projet implémente un système de recommandation d'images modulaire utilisant Docker, PySpark et le paradigme map-reduce.

## Architecture du système

Le système est composé de plusieurs composants indépendants, chacun exécuté dans son propre conteneur Docker :

1. **Orchestrateur** - Coordonne l'ensemble du système et distribue les tâches
2. **Image Downloader (2 instances)** - Télécharge les images à partir de sources externes
3. **Image Tagger (2 instances)** - Analyse et génère des tags et métadonnées pour les images
4. **Recommandation** - Génère des recommandations personnalisées pour les utilisateurs
5. **Base de données (MongoDB)** - Stocke toutes les données du système

Les conteneurs partagent des données via des volumes Docker, permettant un traitement pipeline et une modularité complète.

## Principales fonctionnalités

- Téléchargement parallèle d'images depuis diverses sources
- Analyse d'image et extraction automatique de caractéristiques :
  - Couleurs dominantes avec identification des noms de couleurs
  - Orientation et taille de l'image
  - Tags descriptifs générés automatiquement
- Profilage utilisateur basé sur les préférences (likes/dislikes)
- Système de recommandation personnalisé utilisant PySpark
- Évolutivité horizontale avec possibilité d'ajouter des instances worker supplémentaires

## Technologies utilisées

- **Docker & Docker Compose** - Pour la conteneurisation et l'orchestration
- **MongoDB** - Stockage de données
- **PySpark** - Traitement distribué et parallèle
- **Map-Reduce & Lambda** - Pour l'optimisation des traitements répétitifs
- **Python** - Langage principal de développement
- **OpenCV & scikit-learn** - Pour l'analyse d'images

## Installation et démarrage

1. Assurez-vous que Docker et Docker Compose sont installés sur votre système

2. Clonez ce dépôt :
```bash
git clone <repository-url>
cd Partie2
```

3. Construisez et lancez le système :
```bash
docker-compose build
docker-compose up
```

4. Pour mettre à l'échelle les workers :
```bash
docker-compose up --scale image_downloader=3 --scale image_tagger=4
```

## Dépendances requises

Chaque conteneur installe automatiquement ses propres dépendances grâce aux fichiers requirements.txt. Voici un résumé des principales dépendances :

- **Communes à tous les modules** :
  - pymongo
  - pyspark

- **Image Downloader** :
  - requests
  - Pillow

- **Image Tagger** :
  - opencv-python
  - scikit-learn
  - Pillow
  - numpy

- **Recommandation** :
  - scikit-learn
  - numpy

## Vérification du bon fonctionnement

Pour vérifier que le système fonctionne correctement après l'installation :

1. Examinez les logs des conteneurs :
   ```bash
   docker-compose logs orchestrator
   ```

2. Connectez-vous à la base de données MongoDB :
   ```bash
   docker exec -it partie2_database_1 mongo
   ```
   
   Dans l'interface MongoDB :
   ```
   use imagesdb
   db.images.count()  # Vérifier le nombre d'images téléchargées
   db.tags.count()    # Vérifier le nombre de tags générés
   ```

3. Vérifiez le contenu du volume partagé :
   ```bash
   docker exec -it partie2_orchestrator_1 ls -la /data/images
   ```

## Dépannage

Si vous rencontrez des problèmes :

- **Problèmes de dépendances Python** :
  ```bash
  docker-compose build --no-cache
  ```

- **Problèmes d'accès aux volumes** :
  ```bash
  docker-compose down -v
  docker-compose up
  ```

- **Problèmes de communication avec MongoDB** :
  Vérifiez que la variable d'environnement DATABASE_URL est correctement définie
  dans tous les services du fichier docker-compose.yml

## Volumes Docker et partage de données

Le système utilise deux volumes Docker :
- **shared_data** - Pour partager les images et fichiers communs entre les conteneurs
- **mongo_data** - Pour persister les données MongoDB

## Implémentation de Map-Reduce et Lambda

Chaque module implémente des opérations Map-Reduce et utilise des expressions lambda pour optimiser le traitement des données :

1. **Orchestrateur** - Utilise map-reduce pour distribuer les tâches
2. **Image Downloader** - Téléchargement parallèle d'images avec PySpark RDD
3. **Image Tagger** - Traitement d'images en parallèle avec transformations map
4. **Recommandation** - Calcul parallèle des scores et génération de recommandations

## Architecture de communication

Les conteneurs communiquent principalement via la base de données MongoDB, où ils créent et mettent à jour des documents de tâches. Cette architecture découplée permet une grande flexibilité et évolutivité.

## Extension du système

Le système est conçu pour être facilement extensible :
- Ajoutez de nouvelles sources d'images en modifiant l'orchestrateur
- Créez de nouveaux algorithmes de tagging dans le module image_tagger
- Implémentez des algorithmes de recommandation alternatifs dans le module recommendation
