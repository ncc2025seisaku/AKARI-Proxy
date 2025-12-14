
import sys
import argparse
import logging
from pathlib import Path

# Add 'py' to sys.path if not present, assuming we are running from project root or py/
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from akari.web_proxy.config import load_config
from akari.web_proxy.router import WebRouter
from akari.web_proxy.http_server import WebHttpServer

def main():
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("akari.web_proxy.runner")
    
    parser = argparse.ArgumentParser(description="Akari Web Proxy")
    parser.add_argument("--config", default="conf/web_proxy.toml", help="Path to configuration file")
    args = parser.parse_args()

    config_path = project_root / args.config
    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)
        
    logger.info(f"Starting Web Proxy on {config.listen_host}:{config.listen_port}")
    logger.info(f"Connecting to Remote Proxy at {config.remote.host}:{config.remote.port}")
    
    router = WebRouter(config)
    server = WebHttpServer(config, router)
    server.serve_forever()

if __name__ == "__main__":
    main()
