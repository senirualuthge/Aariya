import logging
import sys
from logging.handlers import RotatingFileHandler

def setup_logging():
    """
    Configure logging for the Agent System.
    """
    logger = logging.getLogger("server.systems.agent")
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler
    file_handler = RotatingFileHandler(
        "agent.log", maxBytes=10*1024*1024, backupCount=5
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Initialize
agent_logger = setup_logging()
