# Guide d'interaction avec le système de recommandation

Ce document explique comment interagir avec le système de recommandation d'images, simuler des actions utilisateurs, et vérifier les résultats.

## 1. Préparation du système

Assurez-vous que tous les services sont opérationnels :

```bash
docker-compose ps
```

## 2. Création d'utilisateurs de test

Connectez-vous à MongoDB et créez quelques utilisateurs de test :

```bash
docker exec -it partie2_database_1 mongosh
```

Une fois dans la console MongoDB :

```javascript
use imagesdb

// Créer des utilisateurs de test
db.users.insertMany([
  { 
    "_id": "user1", 
    "name": "Alice", 
    "preferences": { "genres": ["action", "comedy"], "colors": ["blue", "red"] } 
  },
  { 
    "_id": "user2", 
    "name": "Bob", 
    "preferences": { "genres": ["drama", "documentary"], "colors": ["green", "black"] } 
  },
  { 
    "_id": "user3", 
    "name": "Charlie", 
    "preferences": { "genres": ["sci-fi", "fantasy"], "colors": ["purple", "orange"] } 
  }
])

// Vérifiez que les utilisateurs sont bien créés
db.users.find()
```

## 3. Déclencher manuellement un téléchargement d'images

Pour déclencher manuellement le téléchargement d'images, créez des tâches dans MongoDB :

```javascript
// Dans la console MongoDB

// Créer une tâche pour le downloader 1
db.download_tasks.insertOne({
  "worker_id": 1,
  "urls": [
    "https://picsum.photos/id/1/800/600",
    "https://picsum.photos/id/2/800/600",
    "https://picsum.photos/id/3/800/600",
    "https://picsum.photos/id/4/800/600",
    "https://picsum.photos/id/5/800/600"
  ],
  "status": "pending"
})

// Créer une tâche pour le downloader 2
db.download_tasks.insertOne({
  "worker_id": 2,
  "urls": [
    "https://picsum.photos/id/6/800/600",
    "https://picsum.photos/id/7/800/600",
    "https://picsum.photos/id/8/800/600",
    "https://picsum.photos/id/9/800/600",
    "https://picsum.photos/id/10/800/600"
  ],
  "status": "pending"
})

// Vérifiez que les tâches sont créées
db.download_tasks.find()
```

## 4. Vérifier le téléchargement des images

Vérifiez les logs pour voir si les images sont téléchargées :

```bash
docker-compose logs image_downloader_1
docker-compose logs image_downloader_2
```

Vérifiez également dans MongoDB si les entrées d'images ont été créées :

```javascript
// Dans la console MongoDB
db.images.find().pretty()
```

Vérifiez le répertoire d'images partagé :

```bash
docker exec -it partie2_orchestrator_1 ls -la /data/images
```

## 5. Déclencher manuellement le tagging des images

Attendez que les images soient téléchargées, puis créez des tâches de tagging :

```javascript
// Dans la console MongoDB

// D'abord, obtenez les IDs des images téléchargées
var imageIds = db.images.find({tagged: {$ne: true}}, {_id: 1}).map(function(doc) { return doc._id; });

// Diviser les images entre les deux workers
var imageIds1 = imageIds.slice(0, Math.ceil(imageIds.length / 2));
var imageIds2 = imageIds.slice(Math.ceil(imageIds.length / 2));

// Créer une tâche pour le tagger 1
db.tagging_tasks.insertOne({
  "worker_id": 1,
  "image_ids": imageIds1,
  "status": "pending"
})

// Créer une tâche pour le tagger 2
db.tagging_tasks.insertOne({
  "worker_id": 2,
  "image_ids": imageIds2,
  "status": "pending"
})

// Vérifiez que les tâches sont créées
db.tagging_tasks.find()
```

## 6. Vérifier le tagging des images

Vérifiez les logs pour voir si les images sont taguées :

```bash
docker-compose logs image_tagger_1
docker-compose logs image_tagger_2
```

Vérifiez dans MongoDB si les images ont été mises à jour avec des tags :

```javascript
// Dans la console MongoDB
db.images.find({tagged: true}).pretty()
db.tags.find().pretty()
```

## 7. Simuler des likes/dislikes utilisateurs

Créez des entrées de likes/dislikes pour les utilisateurs :

```javascript
// Dans la console MongoDB

// Obtenez quelques IDs d'images
var allImages = db.images.find({}, {_id: 1}).map(function(doc) { return doc._id; });

// Pour l'utilisateur 1 : aime certaines images
for (var i = 0; i < 3; i++) {
  if (i < allImages.length) {
    db.user_likes.insertOne({
      "user_id": "user1",
      "image_id": allImages[i],
      "liked": true,
      "timestamp": new Date()
    });
  }
}

// Pour l'utilisateur 1 : n'aime pas certaines images
for (var i = 3; i < 5; i++) {
  if (i < allImages.length) {
    db.user_likes.insertOne({
      "user_id": "user1",
      "image_id": allImages[i],
      "liked": false,
      "timestamp": new Date()
    });
  }
}

// Pour l'utilisateur 2 : aime certaines images
for (var i = 2; i < 6; i++) {
  if (i < allImages.length) {
    db.user_likes.insertOne({
      "user_id": "user2",
      "image_id": allImages[i],
      "liked": true,
      "timestamp": new Date()
    });
  }
}

// Vérifiez les likes/dislikes
db.user_likes.find()
```

## 8. Déclencher manuellement des recommandations

Créez une tâche de recommandation :

```javascript
// Dans la console MongoDB

db.recommendation_tasks.insertOne({
  "user_ids": ["user1", "user2", "user3"],
  "status": "pending",
  "created_at": new Date()
})

// Vérifiez que la tâche est créée
db.recommendation_tasks.find()
```

## 9. Vérifier les recommandations générées

Vérifiez les logs pour voir si les recommandations sont générées :

```bash
docker-compose logs recommendation
```

Vérifiez dans MongoDB si des recommandations ont été créées :

```javascript
// Dans la console MongoDB
db.recommendations.find().pretty()
```

## 10. Simuler un flux de travail complet

Voici une séquence pour simuler un flux de travail complet :

1. Ajoutez plus d'images à télécharger
2. Laissez les téléchargeurs faire leur travail
3. Laissez les taggers faire leur travail
4. Ajoutez plus d'interactions utilisateur (likes/dislikes)
5. Déclenchez une nouvelle tâche de recommandation
6. Vérifiez les nouvelles recommandations

Exemple pour l'étape 1 :

```javascript
// Dans la console MongoDB

db.download_tasks.insertOne({
  "worker_id": 1,
  "urls": [
    "https://picsum.photos/id/11/800/600",
    "https://picsum.photos/id/12/800/600",
    "https://picsum.photos/id/13/800/600",
    "https://picsum.photos/id/14/800/600",
    "https://picsum.photos/id/15/800/600"
  ],
  "status": "pending"
})
```

## 11. Visualiser les recommandations (facultatif)

Pour visualiser les recommandations d'une manière plus conviviale, vous pouvez exporter les données et utiliser un outil d'analyse ou créer une petite interface web.

Exportez les recommandations vers un fichier JSON :

```bash
docker exec -it partie2_database_1 mongosh --eval "JSON.stringify(db.recommendations.find().toArray())" imagesdb > recommendations.json
```

## 12. Dépannage

Si certaines étapes ne fonctionnent pas comme prévu :

1. Vérifiez les logs détaillés de chaque service
2. Assurez-vous que MongoDB est accessible à tous les services
3. Vérifiez que les volumes sont correctement montés
4. Vérifiez que les messages entre les services sont correctement transmis via la base de données

## 13. Analyse des résultats

Pour analyser la qualité des recommandations :

```javascript
// Dans la console MongoDB

// Pour un utilisateur spécifique, examinez ses likes et les recommandations
var userId = "user1";
var userLikes = db.user_likes.find({user_id: userId, liked: true}).map(function(doc) { return doc.image_id; });
var userRecommendations = db.recommendations.findOne({user_id: userId});

print("Images aimées par l'utilisateur:");
db.images.find({_id: {$in: userLikes}}, {tags: 1, dominant_colors: 1}).forEach(function(doc) {
  printjson(doc);
});

print("Recommandations pour l'utilisateur:");
if (userRecommendations && userRecommendations.recommendations) {
  userRecommendations.recommendations.forEach(function(rec) {
    printjson(rec);
  });
}
```
