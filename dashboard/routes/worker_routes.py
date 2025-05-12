import traceback
from flask import render_template, redirect, url_for, flash
from app import app
from services.worker_service import get_real_worker_info

@app.route('/workers')
def workers_list():
    """Affiche la liste des workers et leur état"""
    try:
        # Récupérer les données réelles des workers depuis MongoDB
        downloader_workers = []
        for worker_id in range(1, 3):
            worker_info = get_real_worker_info('downloader', worker_id)
            downloader_workers.append(worker_info)
        
        # Taggers d'images
        tagger_workers = []
        for worker_id in range(1, 3):
            worker_info = get_real_worker_info('tagger', worker_id)
            tagger_workers.append(worker_info)
        
        # Service de recommandation
        recommendation_worker = get_real_worker_info('recommendation', 1)
        
        # Statistiques globales
        all_workers = downloader_workers + tagger_workers + [recommendation_worker]
        total_workers = len(all_workers)
        active_workers = sum(1 for w in all_workers if w['status'] == 'active')
        idle_workers = sum(1 for w in all_workers if w['status'] == 'idle')
        offline_workers = sum(1 for w in all_workers if w['status'] == 'offline')
        
        return render_template('workers.html', 
                              downloader_workers=downloader_workers,
                              tagger_workers=tagger_workers,
                              recommendation_worker=recommendation_worker,
                              total_workers=total_workers,
                              active_workers=active_workers,
                              idle_workers=idle_workers,
                              offline_workers=offline_workers)
    except Exception as e:
        traceback.print_exc()
        flash(f"Erreur lors du chargement des informations des workers: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/worker/<worker_type>/<int:worker_id>')
def worker_detail(worker_type, worker_id):
    """Affiche les détails d'un worker spécifique"""
    try:
        # Obtenir uniquement des informations réelles
        worker = get_real_worker_info(worker_type, worker_id)
        
        return render_template('worker_details.html', worker=worker)
    except Exception as e:
        traceback.print_exc()
        flash(f"Erreur lors du chargement des détails du worker: {str(e)}", "danger")
        return redirect(url_for('workers'))
