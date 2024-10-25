import logging


def setup_logger():
  logger = logging.getLogger('maxbot')
  logger.setLevel(logging.INFO)
  loghandler = logging.StreamHandler()
  loghandler.formatter = logging.Formatter(
    '%(levelname)s: %(asctime)s %(filename)s:%(lineno)d %(message)s')
  logger.addHandler(loghandler)
  logger.propagate = False
  return logger


log = setup_logger()
