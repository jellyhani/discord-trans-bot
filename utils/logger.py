import logging
import os
from logging.handlers import TimedRotatingFileHandler


def setup_logger(name: str, log_file: str, level=logging.INFO):
    """
    Sets up a logger with a timed rotating file handler.
    Logs are rotated daily, and 30 days of logs are kept.
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    full_path = os.path.join(log_dir, log_file)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Daily rotation, backupCount=0 (keep all logs indefinitely)
    handler = TimedRotatingFileHandler(full_path, when="midnight", interval=1, backupCount=0, encoding="utf-8")
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers if setup_logger is called multiple times
    if not logger.handlers:
        logger.addHandler(handler)
        
        # Also add a console handler for convenience
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


# Default logger for the bot
tlog = setup_logger("translator", "translator.log")
bot_log = setup_logger("bot", "bot.log")
