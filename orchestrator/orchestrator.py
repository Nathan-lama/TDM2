import os
import time
import logging
import docker
from flask import Flask, jsonify
import threading
import json
import datetime

# Importing the API and autoscaler modules correctly
import autoscaler
import api

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('orchestrator')

# Create Flask app instance
app = Flask(__name__)

# Register API routes
api.init_app(app)

# Initialize Docker client for container management
try:
    docker_client = docker.from_env()
    logger.info("Docker client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Docker client: {e}")
    docker_client = None

# Start autoscaler in a separate thread
def start_autoscaling():
    logger.info("Starting autoscaler thread...")
    while True:
        try:
            autoscaler.check_and_scale(docker_client)
        except Exception as e:
            logger.error(f"Error in autoscaler: {e}")
        
        # Sleep for 30 seconds before next check
        time.sleep(30)

# Only start if Docker client is available
if docker_client:
    autoscaler_thread = threading.Thread(target=start_autoscaling, daemon=True)
    autoscaler_thread.start()
    logger.info("Autoscaler thread started")

if __name__ == "__main__":
    logger.info("Starting orchestrator service...")
    # Start the Flask app
    app.run(host='0.0.0.0', port=5001)
