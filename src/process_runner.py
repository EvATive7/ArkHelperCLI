import pathlib
import threading
import time
import logging
import json
from typing import Optional, Union

from MAA.asst.asst import Asst
from MAA.asst.utils import Message
from model import *
from utils import *


logger: logging.Logger = None
asstproxy: AsstProxy = None
task: dict = None
task_id = None
process_str = None


@Asst.CallBackType
def asst_callback(msg, details, arg):
    try:
        try:
            m = Message(msg)
            d = json.loads(details.decode('utf-8'))
            asstproxy.process_callback(m, d, arg)
        except NameError as e:
            if e.name == 'asstproxy':
                logger.debug(f'asstproxy was deleted when receiving callback: {e}')
            else:
                raise
    except Exception as e:
        logger.error(f'An unexpected error was occured when receiving callback: {e}', exc_info=True)


def start_task_process(process_static_params, process_shared_status):
    global logger, task, task_id, process_str, asstproxy

    device: Device = process_static_params['device']
    task = process_static_params['task']
    task_id = task['hash']
    client_type = task['server']
    process_str = f'taskprocess({task_id})'
    logger = device.logger.getChild(process_str)
    logger.debug('Created')
    logger.info('Ready to execute task')

    result_succeed = False
    result_reason = []
    result_maatasks: list[MaataskRunResult] = []

    try:
        asstproxy = AsstProxy(task_id, logger, device, asst_callback)
        asstproxy.load_res(client_type)
        asstproxy.connect()

        if device.current_status['server'] != client_type:
            if device.current_status['server']:
                device.adb.exec_adb_cmd(f'shell am force-stop {arknights_package_name[device.current_status["server"]]}')
            device.current_status['server'] = client_type

        def update():
            getupdate_support_info = {
                'Official': True,
                'Bilibili': True,
                'YoStarJP': True,
                'YoStarEN': True,
                'YoStarKR': True,
                'txwy': True
            }
            update_support_info = {
                'Official': True,
                'Bilibili': True,
                'YoStarJP': False,
                'YoStarEN': False,
                'YoStarKR': False,
                'txwy': False
            }

            if getupdate_support_info[client_type]:
                local_version = device.adb.get_game_version(client_type)

                need_update = False
                newest = ''
                local = ''

                try:
                    if client_type == 'Official':
                        newest = ArknightsAPI.get_newest_version()
                        local = local_version.replace('.', '')
                        need_update = newest != local
                    elif client_type in ['YoStarJP', 'YoStarEN', 'YoStarKR', 'txwy']:
                        newest = QooAppAPI.get_newest_version(client_type)
                        local = local_version
                        need_update = newest != local
                    elif client_type == 'Bilibili':
                        newest = BiligameAPI.get_newest_version()
                        local = local_version
                        need_update = newest != local
                    logger.debug(f'newest version = {newest}, local version = {local}')
                except Exception as e:
                    logger.warning(f'An unexpected error was occured when getting update: {e}')

                if need_update:
                    if update_support_info[client_type]:
                        try:
                            logger.debug(f'Trying to update')
                            newest_link = ''

                            if client_type == 'Official':
                                newest_link = ArknightsAPI.get_newest_apk_link()
                            elif client_type == 'Bilibili':
                                newest_link = BiligameAPI.get_newest_apk_link()
                            else:
                                ...

                            logger.debug(f'newest link = {newest_link}')
                            download_to = var.cache_path / convert_str_to_legal_filename_windows(f'arknights_{client_type}_{newest}_{int(time.time())}.apk')

                            logger.debug(f'Start to download the newest version')
                            download(newest_link, download_to)

                            logger.debug(f'Start to install')
                            device.adb.install(download_to)

                            download_to.unlink(True)
                            logger.info('Arknights client has been successfully updated')
                        except Exception as e:
                            raise Exception(f'The newest version is {newest} but the local version is {local}. When updating, an error occured: {e}')
                    else:
                        raise Exception(f'The newest version is {newest} but the local version is {local}. The task cannot be run')

        try_run(update, (), 2, 3000)

        remain_time = var.global_config.get('max_task_waiting_time', 3600)
        execute, execute_disabled_by = True, ''
        for maatask in task['task']:
            maatask_name = maatask['task_name']
            if remain_time > 0:
                if execute:
                    run_result = asstproxy.run_maatask(maatask, remain_time)
                    if maatask_name == 'StartUp' and not run_result.exec_result.succeed:
                        execute, execute_disabled_by = False, maatask_name
                    remain_time = run_result.time_remain
                    result_maatasks.append(run_result)
                else:
                    result_maatasks.append(MaataskRunResult(maatask_name, False, [f'Skipped: disabled by {execute_disabled_by}'], 0, 0))
            else:
                result_maatasks.append(MaataskRunResult(maatask_name, False, ['LackTime'], 0, 0))

        # dev.exec_adb(f'shell screencap -p /sdcard/DCIM/AkhCLI_{id}_{int(time.time())}.png')

        result_succeed = all([t.exec_result.succeed for t in result_maatasks])
        result_maatasks = [t.dict() for t in result_maatasks]

        del asstproxy
        logger.debug('Ready to exit')
    except Exception as e:
        result_succeed = False
        error_str = f'An unexpected error was occured when running: {e}'
        result_reason = [error_str]
        result_maatasks = []
        logger.error(error_str, exc_info=True)
    finally:
        process_shared_status['result'] = {
            'task': task_id,
            'exec_result': {
                'succeed': result_succeed,
                'reason': ','.join(result_reason),
                'maatasks': result_maatasks
            }
        }
