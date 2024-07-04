import logging
import sys


def get_logger(logger_name=None):
    if logger_name is None:
        logger_name = "locust_operator"
    logger = logging.getLogger(logger_name)
    logging.basicConfig(
        level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logger
