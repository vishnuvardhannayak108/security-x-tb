from flask import Flask
from threading import Thread
import os
import time
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return '''
    <html>
        <head><title>Discord Bot Status</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
            <h1>🤖 Discord Bot is Running!</h1>
            <p>Your Carl-bot clone is active and ready to serve.</p>
            <p style="color: #5865F2;">Status: ✅ Online</p>
        </body>
    </html>
    '''

@app.route('/health')
def health():
    return {'status': 'ok', 'bot': 'running'}, 200

import logging

logger = logging.getLogger('webserver')

def run():
    """Run the Flask web server."""
    try:
        # Get port from environment variables with fallbacks
        port = int(os.getenv('PORT', os.getenv('SERVER_PORT', 30055)))
        host = os.getenv('SERVER_HOST', '0.0.0.0')
        
        # Suppress Flask startup banner
        import sys
        cli = sys.modules['flask.cli']
        cli.show_server_banner = lambda *x: None
        
        # Listen on configured host and port
        app.run(
            host=host,
            port=port,
            threaded=True,
            debug=False,
            use_reloader=False 
        )
    except Exception as e:
        logger.error(f"Webserver Error: {str(e)}")
        return None

def keep_alive() -> Thread:
    """
    Start the webserver in a background thread.
    
    Returns:
        Thread: The background thread running the webserver, or None if startup failed
    """
    try:
        # Ensure we're not trying to start multiple servers
        for thread in threading.enumerate():
            if thread.name == 'WebserverThread':
                logger.info("Webserver already running")
                return thread
                
        t = Thread(target=run, daemon=True, name='WebserverThread')
        t.start()
        
        # Wait for server to start
        time.sleep(1)
        logger.info(f"Webserver started on port {os.getenv('PORT', os.getenv('SERVER_PORT', 30055))}")
        return t
    except Exception as e:
        logger.error(f"Failed to start webserver: {str(e)}")
        return None

# If this file is run directly, start the webserver
if __name__ == '__main__':
    keep_alive()
