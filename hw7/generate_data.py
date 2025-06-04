# generate_data.py (HW7 适配 v6 - 优先生成 UPDATE)
import random
import time
import math
import bisect
import re
from collections import defaultdict

# --- 常量 (不变) ---
FLOOR_MIN = -4; FLOOR_MAX = 7
VALID_FLOORS = list(range(FLOOR_MIN, 0)) + list(range(1, FLOOR_MAX + 1))
ELEVATOR_COUNT = 6; MAX_TIME_DEFAULT = 100.0; MAX_TIME_MUTUAL = 50.0
UPDATE_TARGET_FLOORS = [-2, -1, 1, 2, 3, 4, 5]; SCHE_TARGET_FLOORS = [-2, -1, 1, 2, 3, 4, 5]
SCHE_SPEEDS_CORRECT = [0.2, 0.3, 0.4, 0.5]; MAX_SCHE_REQUESTS_PUBLIC = 10
MAX_UPDATE_REQUESTS = ELEVATOR_COUNT // 2; MAX_TOTAL_REQUESTS_MUTUAL = 70
MAX_SCHE_PER_ELEVATOR_MUTUAL = 1; MIN_SPECIAL_INTERVAL = 8.0

def floor_to_str(floor):
    if floor < 0: return f"B{-floor}"
    else: return f"F{floor}"

def generate_requests_phased_hw7(
    num_passenger_requests=55,
    num_sche_requests=10, # 目标 SCHE 数量设为 10 左右
    num_update_requests=2, # 目标 UPDATE 数量
    max_time=MAX_TIME_DEFAULT,
    filename="stdin.txt",
    is_mutual_test=False
):
    # --- 应用互测约束 (不变) ---
    if is_mutual_test:
        max_time = MAX_TIME_MUTUAL; num_update_requests = min(num_update_requests, MAX_UPDATE_REQUESTS)
        num_sche_requests = min(num_sche_requests, ELEVATOR_COUNT, 6) # 互测 sche 数量也限制
        total_requests_target = num_passenger_requests + num_sche_requests + num_update_requests
        if total_requests_target > MAX_TOTAL_REQUESTS_MUTUAL:
            diff = total_requests_target - MAX_TOTAL_REQUESTS_MUTUAL
            pass_reduce = min(diff, max(0, num_passenger_requests - 1)); num_passenger_requests -= pass_reduce; diff -= pass_reduce
            if diff > 0: sche_reduce = min(diff, num_sche_requests); num_sche_requests -= sche_reduce; diff -= sche_reduce
            if diff > 0: num_update_requests = max(0, num_update_requests - diff)
        num_passenger_requests = max(1, num_passenger_requests); num_sche_requests = min(num_sche_requests, ELEVATOR_COUNT); num_update_requests = min(num_update_requests, MAX_UPDATE_REQUESTS)
        final_total = num_passenger_requests + num_sche_requests + num_update_requests
        if final_total > MAX_TOTAL_REQUESTS_MUTUAL: print(f"警告: 互测约束调整后总数 ({final_total}) 仍然超过 {MAX_TOTAL_REQUESTS_MUTUAL}。")
    else: # 公测约束
        num_passenger_requests = max(1, min(num_passenger_requests, 100)); num_sche_requests = min(num_sche_requests, MAX_SCHE_REQUESTS_PUBLIC)
        num_update_requests = min(num_update_requests, MAX_UPDATE_REQUESTS);
        if num_passenger_requests == 0: num_passenger_requests = 1

    # --- ID 和状态跟踪 ---
    person_ids = random.sample(range(1, 10001 + num_passenger_requests), num_passenger_requests)
    person_id_index = 0; sche_request_counts = defaultdict(int); updated_elevators = set()
    last_special_request_time_for_elevator = defaultdict(lambda: 0.0) # 初始化为 0.0

    all_generated_requests = [] # 存储所有成功生成的请求 (timestamp, request_str)

    # --- 1. 优先生成 UPDATE 请求 ---
    update_requests_generated = 0
    # 定义目标阶段的时间范围
    phase2_start, phase2_end = max_time * 0.15, max_time * 0.50
    phase4_start, phase4_end = max_time * 0.75, max_time
    update_timestamps_targets = []
    if num_update_requests >= 1: update_timestamps_targets.append(random.uniform(phase2_start, phase2_end))
    if num_update_requests >= 2: update_timestamps_targets.append(random.uniform(phase4_start, phase4_end))
    if num_update_requests >= 3:
        # 第三个也放在第四阶段
        third_ts = random.uniform(phase4_start, phase4_end)
        # 简单处理，避免过于接近第二个（如果存在）
        if len(update_timestamps_targets) > 1 and abs(third_ts - update_timestamps_targets[1]) < 1.0 :
            third_ts = random.uniform(phase4_start, phase4_end) # 再试一次
        update_timestamps_targets.append(third_ts)

    update_timestamps_targets.sort() # 按时间排序尝试生成

    for ts_update in update_timestamps_targets:
        if update_requests_generated >= num_update_requests: break # 如果已达到目标数

        available_elevators = [e for e in range(1, ELEVATOR_COUNT + 1) if e not in updated_elevators]
        if len(available_elevators) < 2: continue # 可用电梯不足

        # 尝试多次选择电梯对，增加成功率
        found_pair = False
        for _ in range(ELEVATOR_COUNT * 2): # 尝试次数上限
            e_a, e_b = random.sample(available_elevators, 2)
            # 检查时间约束
            if ts_update >= last_special_request_time_for_elevator[e_a] + MIN_SPECIAL_INTERVAL and \
               ts_update >= last_special_request_time_for_elevator[e_b] + MIN_SPECIAL_INTERVAL:
                 target_floor = random.choice(UPDATE_TARGET_FLOORS)
                 request_str = f"[{ts_update:.1f}]UPDATE-{e_a}-{e_b}-{floor_to_str(target_floor)}" # 使用 .1f 格式
                 all_generated_requests.append((ts_update, request_str))
                 update_requests_generated += 1
                 updated_elevators.add(e_a); updated_elevators.add(e_b)
                 last_special_request_time_for_elevator[e_a] = ts_update
                 last_special_request_time_for_elevator[e_b] = ts_update
                 found_pair = True
                 break # 找到一对就生成
        # if not found_pair: # 强制时间点找不到合适电梯对，忽略

    # --- 2. 生成 SCHE 请求 ---
    sche_requests_generated = 0
    sche_timestamps = sorted([random.uniform(1.0, max_time) for _ in range(num_sche_requests * 2)]) # 生成稍多时间戳备用

    for ts_sche in sche_timestamps:
        if sche_requests_generated >= num_sche_requests: break

        possible_elevators = [e for e in range(1, ELEVATOR_COUNT + 1) if e not in updated_elevators]
        valid_schedule_elevators = []
        for eid in possible_elevators:
            if is_mutual_test and sche_request_counts[eid] >= MAX_SCHE_PER_ELEVATOR_MUTUAL: continue
            if ts_sche < last_special_request_time_for_elevator[eid] + MIN_SPECIAL_INTERVAL: continue
            valid_schedule_elevators.append(eid)

        if valid_schedule_elevators:
            elevator_id = random.choice(valid_schedule_elevators)
            target_floor = random.choice(SCHE_TARGET_FLOORS); speed = random.choice(SCHE_SPEEDS_CORRECT)
            request_str = (f"[{ts_sche:.1f}]SCHE-{elevator_id}-{speed:.1f}-{floor_to_str(target_floor)}")
            all_generated_requests.append((ts_sche, request_str))
            sche_request_counts[elevator_id] += 1; sche_requests_generated += 1
            last_special_request_time_for_elevator[elevator_id] = ts_sche

    # --- 3. 生成乘客请求 ---
    passenger_reqs_generated = 0
    passenger_timestamps = sorted([random.uniform(1.0, max_time) for _ in range(num_passenger_requests)])

    for ts_p in passenger_timestamps:
        if passenger_reqs_generated >= num_passenger_requests: break
        if person_id_index < len(person_ids):
            pid = person_ids[person_id_index]
            from_floor, to_floor, priority = -99, -99, -1
            # 可以简化乘客生成逻辑，不再分阶段，随机生成
            from_floor=random.choice(VALID_FLOORS)
            possible_tos = list(set(VALID_FLOORS) - {from_floor})
            if not possible_tos: to_floor = 1 if from_floor != 1 else 2 # Fallback
            else: to_floor = random.choice(possible_tos)
            priority = random.randint(1, 100)

            request_str = (f"[{ts_p:.1f}]{pid}-PRI-{priority}-FROM-{floor_to_str(from_floor)}-TO-{floor_to_str(to_floor)}")
            all_generated_requests.append((ts_p, request_str))
            passenger_reqs_generated += 1
            person_id_index += 1

    # --- 4. 合并、排序、调整时间戳、输出 ---
    all_generated_requests.sort(key=lambda x: x[0]) # 按时间戳排序

    final_requests_output = []; last_output_time_numeric = 0.0
    actual_passenger_reqs = 0; actual_sche_reqs = 0; actual_update_reqs = 0

    for req_time_float, req_str_full in all_generated_requests:
        # 解析原始时间戳
        ts_match = re.match(r"\[\s*(\d+\.\d+)\s*\]", req_str_full)
        if not ts_match: continue # 跳过格式错误的（理论上不该有）
        original_ts = float(ts_match.group(1))
        content_part = req_str_full[ts_match.end():]

        # 调整时间戳确保非递减和精度
        output_time_float = round(original_ts, 1)
        if output_time_float < last_output_time_numeric:
            output_time_float = last_output_time_numeric
        # 确保时间戳不小于 1.0
        output_time_float = max(1.0, output_time_float)

        if output_time_float >= max_time: continue # 确保不超过输入截止时间

        # 重构字符串并统计
        reconstructed_str = None
        is_sche = content_part.startswith('SCHE'); is_update = content_part.startswith('UPDATE'); is_passenger = not is_sche and not is_update
        match_passenger = re.match(r"(\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)", content_part)
        match_sche = re.match(r"SCHE-(\d+)-(\d+\.\d+)-([BF]\d+)", content_part)
        match_update = re.match(r"UPDATE-(\d+)-(\d+)-([BF]\d+)", content_part)

        if is_passenger and match_passenger:
            pid, pri, from_s, to_s = match_passenger.groups()
            reconstructed_str = (f"[{output_time_float:.1f}]{pid}-PRI-{pri}-FROM-{from_s}-TO-{to_s}")
            actual_passenger_reqs += 1
        elif is_sche and match_sche:
            el_id, spd_s, floor_s = match_sche.groups()
            try: reconstructed_str = f"[{output_time_float:.1f}]SCHE-{el_id}-{float(spd_s):.1f}-{floor_s}"; actual_sche_reqs += 1
            except ValueError: pass
        elif is_update and match_update:
            e_a, e_b, floor_s = match_update.groups()
            reconstructed_str = f"[{output_time_float:.1f}]UPDATE-{e_a}-{e_b}-{floor_s}"
            actual_update_reqs += 1

        if reconstructed_str:
            final_requests_output.append(reconstructed_str)
            last_output_time_numeric = output_time_float

    final_requests_count = len(final_requests_output)

    # --- 写入文件 ---
    try:
        with open(filename, "w", encoding='utf-8') as f:
            for req_str in final_requests_output: f.write(req_str + "\n")
        print(f"生成了 {final_requests_count} 条请求 ({actual_passenger_reqs} P, {actual_sche_reqs} S, {actual_update_reqs} U) 到 {filename} (模式: {'mutual' if is_mutual_test else 'public'}, 输入截止时间: {max_time:.1f}s)")
        # 保留之前的警告
        if num_update_requests > 0 and actual_update_reqs < num_update_requests:
             print(f"警告: 目标生成 {num_update_requests} 个 UPDATE 请求，但实际只生成了 {actual_update_reqs} 个。")
        if num_update_requests >= 2 and actual_update_reqs < 2:
             print(f"强警告: 目标生成 >= 2 个 UPDATE 请求，但实际生成了 {actual_update_reqs} (< 2) 个！")
        return True
    except IOError as e:
        print(f"写入 {filename} 出错: {e}")
        return False

# --- 主执行逻辑 (不变) ---
if __name__ == '__main__':
    print("为 HW7 生成数据 (默认互测模式)...")
    pass_req = 60; sche_req = 5; upd_req = 2 # 目标值
    if generate_requests_phased_hw7(is_mutual_test=True, filename="stdin.txt",
                                   num_update_requests=upd_req,
                                   num_sche_requests=sche_req,
                                   num_passenger_requests=pass_req):
        print(f"已生成 HW7 的 stdin.txt (互测, 目标: P={pass_req}, S={sche_req}, U={upd_req}).")
    else:
        print("生成 HW7 的 stdin.txt 失败.")