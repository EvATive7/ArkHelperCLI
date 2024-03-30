import var
from Libs.utils import *
from Libs.test import test
from Libs.maa_runner import run

mode = init(main_path=__file__)

if __name__ == '__main__':
    logging.info(f'CLI started up at {var.cli_env}')
    logging.debug(f'With MAA {var.maa_env}')
    logging.debug(f'With global config {var.global_config}')
    logging.debug(f'With config templates {var.config_templates}')
    logging.debug(f'With personal config {var.personal_configs}')

    try:
        entrance = locals()[mode]
        if var.verbose and False:
            run_with_LineProfiler(entrance)
        else:
            entrance()

        logging.info(f'CLI ready to exit')
    except Exception as e:
        logging.critical(f'An unexpected error was occured when running: {e}', exc_info=True)
