from utils import *


def choice_stage(server, preference_dict: dict):
    stages_in_limit_list = [cp for cp in preference_dict if cp.rsplit('-', 1)[0] in arknights_stage_opening_time]
    stages_outof_limit_list = [cp for cp in preference_dict if not cp.rsplit('-', 1)[0] in arknights_stage_opening_time]

    for stage in stages_in_limit_list:
        opening_time = arknights_stage_opening_time[stage.rsplit('-', 1)[0]]

        if in_game_time(datetime.now(), server).weekday() not in opening_time:
            preference_dict.pop(stage)
            continue

        rate_standard_coefficient = len(opening_time)
        preference_dict[stage] /= rate_standard_coefficient  # 平衡概率

    for stage in stages_outof_limit_list:
        preference_dict[stage] /= 7  # 平衡概率

    return random_choice_with_weights(preference_dict)
