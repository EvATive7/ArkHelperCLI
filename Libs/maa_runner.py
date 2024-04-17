import var
from Libs.utils import *
from Libs.model import *
from Libs.process_runner import start_task_process
from Libs.task_planner import *


import logging
import time
import copy
import multiprocessing
from dataclasses import dataclass

from indent_concluder import Item as ConcluderItem


def do_conclusion():
    file_name = r'%y-%m-%d-%H-%M-%S.json'
    file_name = var.start_time.strftime(file_name)

    file = var.cli_env / 'conclusion' / file_name

    def _get_conclusion():
        return {
            'msg': 'AkhCLI任务全部完成',
            'startTime': int(var.start_time.timestamp()*1000),
            'endTime': int(time.time()*1000),
            'code': 0,
            'extra': {}
        }

    file.parent.mkdir(exist_ok=True)
    conclusion = _get_conclusion()

    write_json(file, conclusion)


def get_report(result):
    conclusion_item = []
    for task_id, task_result in result.items():
        if task_result:
            item = ConcluderItem(task_id, task_result['exec_result']['succeed'], '')
            for maatask in task_result['exec_result']['maatasks']:
                item.append(ConcluderItem(maatask['type'], maatask['exec_result']['succeed'], ', '.join(maatask['exec_result']['reason'])))
        else:
            item = ConcluderItem(task_id, False, 'Task failed to run')
        conclusion_item.append(item)
    conclusion_item = '\n'.join([str(i) for i in conclusion_item])

    return \
        f"""ArkHelperCLI has finished all of the tasks
{var.start_time.strftime('%Y-%m-%d %H:%M:%S')} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{conclusion_item}"""


def run():
    update_nav()
    if var.global_config.get('restart_adb', False):
        ADB().exec_adb_cmd(['kill-server', 'start-server'])
    # kill_all_emulators()

    @dataclass
    class DeviceStatus:
        device: Device
        process: multiprocessing.Process | None
        process_static_params: dict | None
        process_shared_status: dict | None
        finished: bool

    [var.tasks.append(get_full_task(personal_config)) for personal_config in var.personal_configs]
    devices = [Device(dev_config) for dev_config in var.global_config['devices']]
    statuses: list[DeviceStatus] = [DeviceStatus(_device, None, None, None, False) for _device in devices]
    running_result = {task.get('hash'): None for task in var.tasks}
    device_count_limit = var.global_config.get('devices_running_limit', 10)

    ...

    while True:
        for status in statuses:
            if status.process != None:
                if not status.process.is_alive():
                    task_hash = status.process_static_params["task"]["hash"]
                    status.device.logger.debug(f'TaskProcess {task_hash} ended, ready to clear')
                    running_result[task_hash] = status.process_shared_status.get('result', None)
                    status.process = None
                    status.process_static_params = None
                    status.process_shared_status = None

        def running_devices_count():
            return len([_status for _status in statuses if _status.process != None and not _status.finished])

        for status in statuses:
            logger = status.device.logger

            if status.finished:
                continue

            if status.process == None:
                _running_devices_count = running_devices_count()

                if _running_devices_count < device_count_limit:
                    logger.debug(f'{_running_devices_count} devices is running. OK for this')
                    logger.debug(f'Process is None, ready to distribute task')

                    def no_task():
                        logger.debug(f'No task to distribute. Ended')
                        if status.device.kill_after_end:
                            status.device.kill()
                        status.finished = True
                    if var.tasks:
                        distribute_task = (
                            [task for task in var.tasks if task.get('device') == status.device.alias] or
                            [task for task in var.tasks if task.get('device') is None] or
                            [None]
                        )[0]

                        if distribute_task:
                            var.tasks.remove(distribute_task)
                            process_static_params = {
                                'task': distribute_task,
                                'device': status.device
                            }
                            process_shared_status = multiprocessing.Manager().dict()
                            process = multiprocessing.Process(target=start_task_process, args=(process_static_params, process_shared_status, ))

                            status.process = process
                            status.process_static_params = process_static_params
                            status.process_shared_status = process_shared_status

                            logger.debug(f'Ready to start a task process(task={distribute_task["hash"]})')
                            process.start()
                        else:
                            no_task()
                    else:
                        no_task()

        if all([_status.finished for _status in statuses]):
            logging.debug(f'All devices ended. Ready to exit')
            break
        else:
            time.sleep(2)

    web_hook('run-finished', report=get_report(running_result))


def get_full_task(config: dict):
    final_maatasks: list = []
    overrides = config.get('override', {})
    server = config.get('client_type', 'Official')
    account_name = config.get('account_name', '')
    template_name = config.get('template', 'default')
    hash = f'{server}{account_name}'
    device = var.global_config.get('task-device', {}).get(hash, None)

    template = var.config_templates[template_name]
    for maatask in template:
        final_task_config: dict = copy.deepcopy(maatask['task_config'])
        final_task_name = copy.deepcopy(maatask['task_name'])

        preference_task_config = overrides.get(final_task_name, {})

        def update_and_match_case():
            nonlocal final_task_config
            final_task_config.update(preference_task_config)

            def get_config(key):
                nonlocal final_task_config
                config = final_task_config[key]

                def aval_expression():
                    def time_between(time_start, time_end):
                        current_time = datetime.now().strftime('%H:%M')
                        start_time_obj = datetime.strptime(time_start, '%H:%M')
                        end_time_obj = datetime.strptime(time_end, '%H:%M')
                        current_time_obj = datetime.strptime(current_time, '%H:%M')
                        return start_time_obj <= current_time_obj <= end_time_obj

                    def date_between(date_start, date_end):
                        current_date = datetime.now().strftime('%Y-%m-%d')
                        start_date_obj = datetime.strptime(date_start, '%Y-%m-%d')
                        end_date_obj = datetime.strptime(date_end, '%Y-%m-%d')
                        current_date_obj = datetime.strptime(current_date, '%Y-%m-%d')
                        return start_date_obj <= current_date_obj <= end_date_obj

                    def datetime_between(datetime_start, datetime_end):
                        current_datetime = datetime.now()
                        start_datetime_obj = datetime.strptime(datetime_start, '%Y-%m-%d %H:%M:%S')
                        end_datetime_obj = datetime.strptime(datetime_end, '%Y-%m-%d %H:%M:%S')
                        return start_datetime_obj <= current_datetime <= end_datetime_obj

                    AM = in_game_time(datetime.now(), server).hour < 12
                    weekday = datetime.now().weekday()
                    # excuted_time_in_cur_gameday =

                    return locals().copy()

                if type(config) == dict:
                    try:
                        for case in config:
                            case_config = config[case]
                            if case.replace(' ', '') in ['', 'default']:
                                case = 'True'
                            case_eval = eval(case, {}, aval_expression())
                            if type(case_eval) != bool:
                                raise Exception()
                            if case_eval:
                                return case_config
                            else:
                                continue
                    except:
                        return config
                else:
                    return config
            final_task_config = {key: get_config(key) for key in final_task_config}

        def append():
            if final_task_config.get('enable', True):
                final_maatasks.append({
                    'task_name': final_task_name,
                    'task_config': final_task_config
                })

        update_and_match_case()
        if final_task_name == 'StartUp':
            final_task_config['client_type'] = server
            final_task_config['account_name'] = account_name
        elif final_task_name == 'Fight':
            stage = final_task_config.get('stage')
            if stage and type(stage) == dict:
                final_task_config['stage'] = choice_stage(server, stage)
        else:
            pass
        append()

    if (index := len([t for t in var.tasks if t['hash'] == hash])) != 0:
        hash += f'_{index}'

    task = {
        'hash': hash,
        'task': final_maatasks,
        'device': device,
        'server': server,
        'account_name': account_name
    }
    logging.debug(f'Initialization ended for task {hash}: {task}')
    return task
