import os
import ctypes
import hashlib
import json
import logging
import random
import threading
import time
import tqdm
import psutil
import argparse
import subprocess
import requests
import yaml
import pytz
import colorlog
from io import StringIO
from urllib.parse import quote
from typing import Callable
from pathlib import Path
from datetime import datetime, timezone, timedelta
from line_profiler import LineProfiler  # do not remove this. It's needed by main.py, passing by import *

import var


def init(main_path):
    mode, verbose = parse_arg()

    var.start_time = datetime.now()
    var.cli_env = Path(main_path, '../')
    var.data_path = var.cli_env / 'Data'
    var.config_path = var.data_path / 'Config'
    var.log_path = var.data_path / 'Log'
    var.static_path = var.data_path / 'Static'
    var.cache_path = var.data_path / 'Cache'

    var.global_config = read_config('global')
    var.personal_configs = read_config('personal')
    var.config_templates = get_config_templates()
    var.tasks = []
    var.maa_env = Path(var.global_config['maa_path'])
    var.maa_usrdir_path = var.maa_env / f'userdir'
    var.verbose = verbose

    mk_CLI_dir()
    logging.basicConfig(level=logging.DEBUG, handlers=get_logging_handlers())

    return mode


def mk_CLI_dir():
    var.data_path.mkdir(exist_ok=True)
    var.config_path.mkdir(exist_ok=True)
    var.log_path.mkdir(exist_ok=True)
    var.static_path.mkdir(exist_ok=True)
    var.cache_path.mkdir(exist_ok=True)
    var.maa_usrdir_path.mkdir(exist_ok=True)


def run_with_LineProfiler(func, *args, **kwargs):
    profile = LineProfiler(func)
    result = profile.runcall(func, *args, **kwargs)

    stream = StringIO()
    profile.print_stats(stream=stream)

    logging.debug(stream.getvalue())
    return result


def web_hook(event, report=None):
    vars_for_hook = [('#{'+k+'}', v) for k, v in locals().copy().items() if k != 'vars_for_hook']

    for webhook_config in var.global_config.get('webhook', []):
        webhook_on = webhook_config.get('on', 'all')
        if type(webhook_on) == list:
            if not event in webhook_on:
                continue
        elif type(webhook_on) == str:
            if not webhook_on in ['all', event]:
                continue

        def replace_var(text: str, exec_quote=False) -> str:
            def replace_escape(es: str) -> str:
                if True:
                    es = es.replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r')
                if exec_quote:
                    es = quote(es)
                return es

            for origin, after in vars_for_hook:
                text = text.replace(origin, replace_escape(after))
            return text

        if webhook_body := webhook_config.get('body'):
            webhook_method = 'POST'
            webhook_body = replace_var(webhook_body).encode()
        else:
            webhook_method = 'GET'
        webhook_url = replace_var(webhook_config['url'], exec_quote=True)
        webhook_headers = {'X-ArkHelper-Event': '#{event}'}
        webhook_headers.update(webhook_config.get('headers', {}))
        webhook_headers = {replace_var(k): replace_var(v) for k, v in webhook_headers.items()}

        try:
            logger = logging.getLogger(f'Webhook: {webhook_method} {webhook_url}')
            logger.debug(f'Start to webhook')
            webhook_response = requests.request(webhook_method, webhook_url, data=webhook_body, headers=webhook_headers, timeout=10)
            webhook_result = f'{webhook_response.status_code} {webhook_response.text}'
            if webhook_response.ok:
                logger.debug(webhook_result)
            else:
                logger.warning(webhook_result)
        except Exception as e:
            logger.error(f'{e}')


def convert_str_to_legal_filename_windows(filename):
    end = ''
    for char in filename:
        if not char in ['\\', '/', ':', '*', '?', '\"', '<', '>', '|']:
            end += char
    return end


def walk_dir(path):
    result = []
    for home, dirs, files in os.walk(path):
        for filename in files:
            result.append(filename)
    return result


def get_config_templates():
    result = {}
    for file in walk_dir(var.config_path):
        if file.startswith('template_') and (file.endswith('.yaml') or file.endswith('.yml')):
            result[file.replace('.yml', '').replace('.yaml', '').replace('template_', '')] = read_yaml(var.config_path / file)
    return result


def is_process_running(process_name):
    for process in psutil.process_iter(['name']):
        try:
            process_info = process.info
            if process_info['name'] == process_name:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False


def get_pid_by_port(port) -> int | None:
    '''
    Can safely pass in None (return None)
    '''
    if port:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == int(port):
                return conn.pid
    return None


def get_process_info(pid):
    try:
        process = psutil.Process(pid)
        return process
    except psutil.NoSuchProcess as e:
        logging.error(f'Get process failed: {e}')


def parse_arg():
    parser = argparse.ArgumentParser(add_help=False)

    parser.add_argument('-h', '--help', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')

    subparsers = parser.add_subparsers(title='Subcommands', dest='subcommand')

    subparser_run = subparsers.add_parser('run', help='Start running MAA according to config. ')
    subparser_test = subparsers.add_parser('test', help='Mode for develop. ')
    # subparser_run.add_argument('arg1')

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        exit(0)

    mode = args.subcommand
    verbose = args.verbose

    return mode, verbose


def get_cur_time_f_hhmm():
    current_time = datetime.now()
    current_hour = current_time.hour
    current_minute = current_time.minute
    return current_hour*100+current_minute


def read_file(path):
    with open(str(path), 'r', encoding='utf8') as file:
        return file.read()


def read_json(path):
    return json.loads(read_file(path))


def read_yaml(path):
    return yaml.safe_load(read_file(path))


def write_file(path, content):
    with open(str(path), 'w', encoding='utf8') as file:
        file.write(content)


def write_json(path, content):
    write_file(path, json.dumps(content, ensure_ascii=False))


def write_yaml(path, content):
    write_file(path, yaml.safe_dump(content))


def read_config(config_name):
    data = read_yaml(var.config_path / f'{config_name}.yaml')
    return data


def get_logging_handlers():
    file_level, console_level = logging.DEBUG, logging.DEBUG if var.verbose else logging.INFO
    log_file = var.log_path / 'log.log'
    format = '%(asctime)s[%(levelname)s][%(name)s] %(message)s'

    if not log_file.exists():
        log_file.parent.mkdir(exist_ok=True)
        log_file.touch()

    try:
        adjust_log_file()
    except:
        pass

    file_handler = logging.FileHandler(str(log_file), encoding='utf-8')
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(format))

    console_handler = colorlog.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(colorlog.ColoredFormatter(
        f'%(log_color)s{format}',
        log_colors={
            'DEBUG': 'reset',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold_red',
        }
    ))

    return [file_handler, console_handler]


def kill_processes_by_name(process_name) -> bool:
    logging.debug(f'killing process {process_name}')
    try:
        result = subprocess.run(['taskkill', '/F', '/IM', f'{process_name}'], check=True, capture_output=True, text=True)
        logging.debug(f'killing result:{result.stdout}')
        return True
    except subprocess.CalledProcessError as e:
        logging.warning(f'killing result:{e.stderr}')
        return False


def kill_processes_by_pid(pid) -> bool:
    logging.debug(f'killing process {pid}')
    try:
        result = subprocess.run(['taskkill', '/F', '/PID', f'{pid}'], check=True, capture_output=True, text=True)
        logging.debug(f'Killing result:{result.stdout}')
        return True
    except subprocess.CalledProcessError as e:
        logging.warning(f'Killing result:{e.stderr}')
        return False


def get_process_command_line(pid):
    try:
        process = psutil.Process(pid)
        command_line = process.cmdline()
        return command_line
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        print(f'Error: {e}')
        return None


def get_process_start_location(pid):
    try:
        process = psutil.Process(pid)
        start_location = process.exe()
        return start_location
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        print(f'Error: {e}')
        return None


def get_pids_by_process_name(process_name):
    matching_pids = []
    for process in psutil.process_iter(['pid', 'name']):
        try:
            process_info = process.info
            if process_info['name'] == process_name:
                matching_pids.append(process_info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return matching_pids


def prase_MuMuVMMHeadless_commandline(headless_pid) -> dict:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--comment')

    parsed, unknown = parser.parse_known_args(get_process_command_line(headless_pid)[1:])
    return {
        'index': parsed.comment.split('-')[-1]
    }


def prase_MuMuPlayer_commandline(player_pid) -> dict:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-v')

    parsed, unknown = parser.parse_known_args(get_process_command_line(player_pid)[1:])
    return {
        'index': parsed.v if parsed.v else '0'
    }


def get_MuMuPlayer_by_MuMuVMMHeadless(headless_pid) -> int | None:
    '''
    Can safely pass in None (return None)
    '''
    if not headless_pid:
        return None
    index = prase_MuMuVMMHeadless_commandline(headless_pid)['index']
    player_pids = [p for p in get_pids_by_process_name('MuMuPlayer.exe') if prase_MuMuPlayer_commandline(p)['index'] == index]
    if player_pids:
        return player_pids[0]
    else:
        return None


def in_game_time(time, server='Official'):
    if server in ('Official', 'Bilibili', 'txwy'):
        zone = pytz.timezone('Asia/Shanghai')  # Asia/Taipei
    elif server in ('YoStarJP', 'YoStarKR'):
        zone = pytz.timezone('Asia/Tokyo')  # Asia/Seoul
    elif server in ('YoStarEN'):
        zone = pytz.timezone('GMT')
    else:
        zone = pytz.timezone('Asia/Shanghai')
    return (time.astimezone(timezone.utc)-timedelta(hours=4)).replace(tzinfo=pytz.utc).astimezone(zone)


def byte_to_MB(byte):
    return byte / (1024**2)


def adjust_log_file():
    log_file = var.log_path / 'log.log'
    log_backup_file = var.log_path / 'log.log.bak'
    if log_file.exists():
        if byte_to_MB(log_file.stat().st_size) > 20:
            if log_backup_file.exists():
                log_backup_file.unlink()
            log_file.rename(log_backup_file)


# stage_opening_time, where Monday == 0 ... Sunday == 6.
arknights_stage_opening_time = {
    'SK': [0, 2, 4, 5],
    'AP': [0, 3, 5, 6],
    'CA': [1, 2, 4, 6],
    'CE': [1, 3, 5, 6],
    'LS': [0, 1, 2, 3, 4, 5, 6],
    'PR-A': [0, 3, 4, 6],
    'PR-B': [0, 1, 4, 5],
    'PR-C': [2, 3, 5, 6],
    'PR-D': [1, 2, 5, 6]
}

arknights_package_name = {
    'Official': 'com.hypergryph.arknights',
    'Bilibili': 'com.hypergryph.arknights.bilibili',
    'YoStarJP': 'com.YoStarJP.Arknights',
    'YoStarEN': 'com.YoStarEN.Arknights',
    'YoStarKR': 'com.YoStarKR.Arknights',
    'txwy': 'tw.txwy.and.arknights'
}


def random_choice_with_weights(dict):
    # 样本数据
    items = []

    # 对应的权重
    weights = []

    for i in dict:
        items.append(i)
        weights.append(dict[i])

    return random.choices(items, weights)[0]


def generate_hash(input_string):
    # 使用SHA-256哈希函数
    hash_object = hashlib.sha256(input_string.encode())
    # 获取十六进制表示的哈希值
    hex_dig = hash_object.hexdigest()
    # 截取前六位作为哈希
    six_digit_hash = hex_dig[:6]
    return six_digit_hash


def update_nav():
    path = var.maa_env

    need_update = False

    last_update_time_file_server = 'https://ota.maa.plus/MaaAssistantArknights/api/lastUpdateTime.json'
    last_update_time_file_local = path / 'cache' / 'resource' / 'lastUpdateTime.json'
    try:
        last_update_time_local = read_json(last_update_time_file_local)['timestamp']
    except:
        last_update_time_file_local.parent.mkdir(parents=True, exist_ok=True)
        write_file(last_update_time_file_local, '')
        last_update_time_local = 0

    last_update_time_content_server = requests.get(last_update_time_file_server, timeout=10).content
    last_update_time_server = json.loads(last_update_time_content_server)['timestamp']

    if last_update_time_local < last_update_time_server:
        need_update = True

    logging.debug(f'Tasks resource last update time is {last_update_time_local} and the data on server is {last_update_time_server}. need to update is {need_update}')

    if need_update:
        ota_tasks_url = 'https://ota.maa.plus/MaaAssistantArknights/api/resource/tasks.json'
        ota_tasks_path = path / 'cache' / 'resource' / 'tasks.json'

        ota_tasks_path.parent.mkdir(parents=True, exist_ok=True)
        write_file(ota_tasks_path, requests.get(ota_tasks_url, timeout=10).content.decode('utf-8'))
        logging.debug(f'Asst tasks updated')

        write_file(last_update_time_file_local, last_update_time_content_server.decode('utf-8'))
        logging.debug(f'Last update time updated')

    pass


def try_run(func: Callable, args: tuple, max_try_time=5, timeout=10, logger=None):
    func_with_arg_str = f"{func.__name__}{str(args)}"

    if not logger:
        logger = logging.getLogger(func_with_arg_str)

    class ThreadWithException(threading.Thread):
        def __init__(self, name):
            threading.Thread.__init__(self)
            self.name = name
            self.result = None

        def run(self):
            # target function of the thread class
            try:  # 用try/finally 的方式处理exception，从而kill thread
                func(*args)
            except Exception as e:
                logger.warning(f"Exception: {e}")
                self.result = e
                self.stop()

        def get_id(self):
            if hasattr(self, '_thread_id'):
                return self._thread_id
            for id, thread in threading._active.items():
                if thread is self:
                    return id

        def stop(self):
            thread_id = self.get_id()
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id,
                                                             ctypes.py_object(SystemExit))
            if res > 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)

    for try_time in range(max_try_time):
        logger.debug(f'{try_time+1}st/{max_try_time}max trying')
        thread = ThreadWithException(func_with_arg_str)
        thread.start()
        thread.join(timeout)
        result = thread.result
        if not thread.is_alive() and not type(thread.result) == Exception:
            return True, result
        else:
            logger.warning(f'{try_time+1}st/{max_try_time}max failed')
            thread.stop()
            thread.join(timeout)
            del thread
            continue

    return False, result


def download(url, path):
    path = str(path)
    logging.debug(f'Start to download from {url} to {path}')
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))

    if response.status_code == 200:
        with open(path, 'wb') as file, tqdm.tqdm(
                total=total_size, unit='B', unit_scale=True, desc=path, ascii=True) as progress_bar:
            for data in response.iter_content(chunk_size=4096):
                file.write(data)
                progress_bar.update(len(data))
        return path
    else:
        raise Exception(f'Download failed: {response.status_code}')
