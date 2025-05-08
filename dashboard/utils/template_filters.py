from datetime import datetime
from config import app

# Enregistrer le filtre pour convertir les timestamps
@app.template_filter('timestamp_to_date')
def timestamp_to_date(value):
    """Converts a timestamp to a formatted date string, handles both int and datetime objects"""
    if value is None:
        return ""
    
    # If the value is already a datetime object
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    
    # If it's a numeric timestamp
    try:
        timestamp = float(value)
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        # If conversion fails, return the original value as string
        return str(value)
