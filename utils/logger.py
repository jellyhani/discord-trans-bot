import logging
import os
from logging.handlers import TimedRotatingFileHandler


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    Windows-safe wrapper for TimedRotatingFileHandler.
    Catches PermissionError [WinError 32] during rollover and ignores it,
    allowing the bot to continue logging to the same file.
    """
    def rotate(self, source, dest):
        try:
            # If the destination file already exists, attempt to remove it
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except (PermissionError, OSError):
                    # Destination is also locked, give up this rotation
                    return
            
            # Perform the rename (rotation)
            os.rename(source, dest)
        except (PermissionError, OSError):
            # File is locked (WinError 32). Gracefully skip rotation.
            # The next 'emit' will try again if the rollover interval is still valid.
            pass


def setup_logger(name: str, log_file: str, level=logging.INFO):
    """
    Sets up a logger with a timed rotating file handler.
    Logs are rotated daily, and all logs are kept.
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    full_path = os.path.join(log_dir, log_file)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Use custom SafeTimedRotatingFileHandler
    handler = SafeTimedRotatingFileHandler(full_path, when="midnight", interval=1, backupCount=0, encoding="utf-8")
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


# Default loggers
tlog = setup_logger("translator", "translator.log")
bot_log = setup_logger("bot", "bot.log")
mentor_log = setup_logger("mentor", "mentor.log", level=logging.DEBUG)
