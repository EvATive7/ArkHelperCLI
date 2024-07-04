from dataclasses import dataclass
import multiprocessing
import os
import pathlib
import threading
import time
import logging
import json
from typing import Optional, Union, TypeVar
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

import var
from Libs.MAA.asst.asst import Asst
from Libs.MAA.asst.utils import Message
from Libs.utils import *

T = TypeVar('T', str, list[str])


class ADB:
    def __init__(self, device: str = None) -> None:
        self.device = device

    def exec_adb_cmd(self, cmd: T, each_timeout=None) -> T:
        type_of_cmd = type(cmd)

        if type_of_cmd == str:
            return self._exec_adb_cmd(cmd, each_timeout)
        if type_of_cmd == list:
            return [self._exec_adb_cmd(c, each_timeout) for c in cmd]

    def _exec_adb_cmd(self, cmd, timeout):
        device = self.device
        final_cmd = var.global_config['adb_path']
        if device:
            final_cmd += f' -s {str(device)}'
        final_cmd += f' {cmd}'

        logging.debug(f'Execing adb cmd: {final_cmd}')
        proc = subprocess.Popen(
            final_cmd,
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True)
        outinfo, errinfo = proc.communicate(timeout=timeout)
        try:
            outinfo = outinfo.decode('utf-8')
        except:
            outinfo = outinfo.decode('gbk')
        try:
            errinfo = errinfo.decode('utf-8')
        except:
            errinfo = errinfo.decode('gbk')

        result = outinfo + errinfo
        logging.debug(f'adb output: \n{result}')
        return result

    def get_game_version(self, game_type):
        package_name = arknights_package_name[game_type]
        result = self.exec_adb_cmd(f'shell "pm dump {package_name} | grep versionName"', each_timeout=5)

        return result.replace(' ', '').replace('versionName=', '').replace('\r\n', '')

    def install(self, path):
        self.exec_adb_cmd(f'install {path}')


class Device:
    def __init__(self, dev_config) -> None:
        self._adb = var.global_config['adb_path']
        self.alias = dev_config['alias']
        self._host = dev_config['emulator_address'].split(':')[0]
        self._port = dev_config['emulator_address'].split(':')[-1]
        self.kill_after_end = dev_config.get('kill_after_end', True)
        self._process = dev_config.get('process')
        self.logger = logging.getLogger(str(self))
        self.current_status = multiprocessing.Manager().dict()
        self.current_status['server'] = None
        self.adb = ADB(self.addr)

        self.logger.debug(f'{self} inited')

    def __str__(self) -> str:
        return f'{self.alias}({self.addr})'

    @property
    def addr(self) -> str:
        return f'{self._host}:{self._port}'

    def kill(self):
        self.logger.debug(f'Try to kill emulator')

        if type(self._process) == None:
            pass
        elif type(self._process) == list:
            for pim in self._process:
                kill_processes_by_name(pim)
        elif type(self._process) == str:
            if self._process == 'mumu':
                headless_pid = get_pid_by_port(self._port)
                player_pid = get_MuMuPlayer_by_MuMuVMMHeadless(headless_pid)
                kill_processes_by_pid(headless_pid)
                kill_processes_by_pid(player_pid)


class DictProxy:
    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._target_dict = {}

    def __getitem__(self, key):
        # self._logger.debug(f"Getting item with key: {key}")
        return self._target_dict[key]

    def __setitem__(self, key, value):
        self._logger.debug(f"Setting item with key: {key} and value: {value}")
        self._target_dict[key] = value

    def __delitem__(self, key):
        self._logger.debug(f"Deleting item with key: {key}")
        del self._target_dict[key]

    def __len__(self):
        return len(self._target_dict)

    def __iter__(self):
        return iter(self._target_dict)

    def __contains__(self, item):
        return item in self._target_dict

    def __repr__(self):
        return repr(self._target_dict)


class AsstProxy:

    def __init__(self, id, last_logger: logging.Logger, device: Device, asst_callback: Asst.CallBackType) -> None:
        self._proxy_id = id
        self._logger = last_logger.getChild(str(self))
        self.device = device
        self.status = DictProxy(self._logger.getChild('maastatus'))
        self.status['current_maatask_status'] = (None, None, None)
        self.status['current_sanity'] = 0
        self.status['max_sanity'] = 0

        self.userdir: pathlib.Path = var.maa_usrdir_path / convert_str_to_legal_filename_windows(self._proxy_id)
        self.userdir.mkdir(exist_ok=True)

        try_run(Asst.load, (var.maa_env, ), 2, 5, self._logger)
        self.asst = Asst(asst_callback)

    def load_res(self, client_type: Optional[Union[str, None]] = None):
        incr: pathlib.Path
        if client_type in ['Official', 'Bilibili', None]:
            incr = var.maa_env / 'cache'
        else:
            incr = var.maa_env / 'resource' / 'global' / str(client_type)

        self._logger.debug(f'Start to load asst resource and lib from incremental path {incr}')
        if not try_run(Asst.load, (var.maa_env, incr, self.userdir), 2, 5, self._logger)[0]:
            raise Exception('Asst failed to load resource')
        self._logger.debug(f'Asst resource and lib loaded from incremental path {incr}')

    def connect(self):

        max_try_time = 50
        for tried_time in range(max_try_time):
            self._logger.debug(f'Connect emulator {tried_time}st/{max_try_time}trying')

            if self.asst.connect(self.device._adb, self.device.addr):
                self._logger.debug(f'Connected to emulator')
                return
            else:
                self._logger.debug(f'Connect failed')

            # if not _execed_start:
            #    self.device.kill_start()
            #    _execed_start = True

            time.sleep(2)
        raise Exception('Connect emulator trying times reached the maximum')

    def add_maatask(self, task_name, task_config):
        self._logger.debug(f'Ready to append task {task_name} to {self}')
        append_result = self.asst.append_task(task_name, task_config)
        if append_result == 0:
            raise Exception(f'Failed to add task {task_name}')

    def add_maatasks(self, task):
        for maatask in task['task']:
            self.add_maatask(maatask)

    def process_callback(self, msg: Message, details: dict, arg):
        self._logger.debug(f'Got callback: {msg},{arg},{details}')
        if msg in [Message.TaskChainExtraInfo, Message.TaskChainCompleted, Message.TaskChainError, Message.TaskChainStopped, Message.TaskChainStart]:
            self.status['current_maatask_status'] = (msg, details, arg)
        elif msg == Message.SubTaskExtraInfo:
            if details.get('class', '') == 'asst::SanityBeforeStageTaskPlugin':
                detail = details.get('details', {})
                self.status['current_sanity'] = detail.get('current_sanity', 0)
                self.status['max_sanity'] = detail.get('max_sanity', 0)

    def run_maatask(self, maatask, time_remain) -> 'MaataskRunResult':
        type = maatask['task_name']
        config = maatask['task_config'].copy()
        self._logger.info(f'Start maatask {type}, time {time_remain} sec')

        i = 0
        max_try_time = 2

        if type == 'Fight':
            stage = config['stage']
            standby_stage = config['standby_stage']
            config.pop('standby_stage')
            fight_ok = True
            fight_reason = ''

        for i in range(max_try_time):
            self._logger.info(f'Maatask {type} {i+1}st/{max_try_time}max trying')

            try:
                if type == 'Fight':
                    if i == 0:
                        config['stage'] = stage
                    else:
                        config['stage'] = standby_stage

                self.add_maatask(type, config)
                if not self.asst.start():
                    raise Exception('Failed to start maa')
                self._logger.debug('Asst start invoked')
                asst_stop_invoked = False
                interval = 5
                while self.asst.running():
                    time.sleep(interval)
                    time_remain -= interval
                    if time_remain < 0:
                        if not asst_stop_invoked and type != 'Fight':
                            self._logger.warning(f'Task time remains {time_remain}')
                            self.asst.stop()
                            self._logger.debug(f'Asst stop invoked')
                            asst_stop_invoked = True
                self._logger.debug(f'Asst running status ended')
                self._logger.debug(f'current_maatask_status={self.status["current_maatask_status"]}')
                if self.status["current_maatask_status"][0] == Message.TaskChainError:
                    if type == "StartUp":
                        self.device.adb.exec_adb_cmd(f'shell am force-stop {arknights_package_name[self.device.current_status["server"]]}')
                    continue
                elif self.status["current_maatask_status"][0] == Message.TaskChainStopped:
                    break
                else:
                    if type == 'Fight':
                        fight_ok = True
                        current_sanity = self.status['current_sanity']
                        max_sanity = self.status['max_sanity']
                        if current_sanity > max_sanity / 3:
                            fight_ok = False
                            fight_reason = f'current_sanity({current_sanity}) > max_sanity({max_sanity})/3, may failed'
                            if i == 0:
                                continue
                    break
            except Exception as e:
                self._logger.info(f'Maatask {type} {i+1}st/{max_try_time}max trying failed: {e}')

        self._logger.debug(f'Maatask {type} ended')
        status_message = self.status["current_maatask_status"][0]
        self._logger.debug(f'Status={status_message}, time_remain={time_remain}')

        def get_result():
            reason = [status_message.name]

            status_ok = status_message == Message.TaskChainCompleted
            time_ok = time_remain >= 0

            if not time_ok:
                reason.append('Timeout')

            succeed = status_ok and time_ok

            if type == 'Fight':
                if not fight_ok:
                    reason.append(fight_reason)
                succeed = succeed and fight_ok

            return succeed, reason

        succeed, reason = get_result()
        reason_str = ','.join(reason)

        if succeed:
            self._logger.info(f'Maatask {type} ended successfully beacuse of {reason_str}')
        else:
            self._logger.warning(f'Maatask {type} ended in failure beacuse of {reason_str}')
        return MaataskRunResult(type, succeed, reason, i+1, time_remain)

    def __str__(self) -> str:
        return f'asstproxy({self._proxy_id})'

    def __del__(self):
        del self.asst


class MaataskRunResult:
    @dataclass
    class MaataskExecResult:
        succeed: str
        reason: str
        tried_times: int

    def __init__(self, type, succeed, reason, tried_times, time_remain) -> None:
        self.type = type
        self.exec_result = MaataskRunResult.MaataskExecResult(succeed, reason, tried_times)
        self.time_remain = time_remain

    def dict(self):
        return {
            'type': self.type,
            'exec_result': {
                'succeed': self.exec_result.succeed,
                'reason': self.exec_result.reason,
                'tried_times': self.exec_result.tried_times
            },
            'time_remain': self.time_remain
        }


class ArknightsAPI:
    _newest_link = None

    def get_newest_version() -> str:
        '''return 2221 if version is 2.2.21'''
        return ArknightsAPI.get_newest_apk_link().split('/')[-1].replace('.apk', '').split('-')[-1]

    def get_newest_apk_link() -> str:
        if not ArknightsAPI._newest_link:
            ArknightsAPI._newest_link = requests.get('https://ak.hypergryph.com/downloads/android_lastest', allow_redirects=False, timeout=10).headers['Location']
        return ArknightsAPI._newest_link


class BiligameAPI:
    def get_newest_version() -> str:
        '''return version'''
        return requests.get('https://line1-h5-pc-api.biligame.com/game/detail/content?game_base_id=101772', timeout=10).json()['data']['android_version']

    def get_newest_apk_link() -> str:
        return requests.get('https://line1-h5-pc-api.biligame.com/game/detail/gameinfo?game_base_id=101772', timeout=10).json()['data']['android_download_link']


class QooAppAPI:
    def get_newest_version(client_type) -> str:
        '''return version'''
        id_list = {
            'YoStarJP': 7117,
            'YoStarEN': 9404,
            'YoStarKR': 9419,
            'txwy': 23510
        }
        id = id_list[client_type]
        ua = UserAgent().random
        html = requests.get(f'https://apps.qqaoop.com/app/{id}', headers={'User-Agent': ua}, timeout=10).text
        soup = BeautifulSoup(html, 'html.parser')
        ld_json_scripts = soup.find_all('script', type="application/ld+json")
        for script in ld_json_scripts:
            json_data = json.loads(script.string)
            if ver := json_data.get('softwareVersion'):
                return ver
        raise Exception(f'Failed to get the newest version of {client_type}')
