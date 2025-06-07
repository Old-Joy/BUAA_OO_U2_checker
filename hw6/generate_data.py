import random
import re

FLOOR_MIN = -4
FLOOR_MAX = 7
VALID_FLOORS = list(range(FLOOR_MIN, 0)) + list(range(1, FLOOR_MAX + 1))
ELEVATOR_COUNT = 6

MAX_TIME_DEFAULT = 60.0
MAX_TIME_MUTUAL = 50.0
SCHE_TARGET_FLOORS = [-2, -1, 1, 2, 3, 4, 5]
SCHE_SPEEDS_CORRECT = [0.2, 0.3, 0.4, 0.5]
MAX_SCHE_REQUESTS_PUBLIC = 20
MAX_SCHE_PER_ELEVATOR_MUTUAL = 1
MAX_TOTAL_REQUESTS_MUTUAL = 70
MIN_SCHE_INTERVAL_ESTIMATE = 15.0

def floor_to_str(floor):
    if floor < 0: return f"B{-floor}"
    else: return f"F{floor}"

def generate_requests_phased_hw6(
    num_passenger_requests=55,
    num_sche_requests=5,
    max_time=MAX_TIME_DEFAULT,
    filename="stdin.txt",
    is_mutual_test=False
):
    if is_mutual_test:
        max_time = MAX_TIME_MUTUAL
        total_requests_target = num_passenger_requests + num_sche_requests
        if total_requests_target > MAX_TOTAL_REQUESTS_MUTUAL:
            scale_factor = MAX_TOTAL_REQUESTS_MUTUAL / total_requests_target
            num_passenger_requests = int(num_passenger_requests * scale_factor)
            num_sche_requests = min(MAX_TOTAL_REQUESTS_MUTUAL - num_passenger_requests, ELEVATOR_COUNT)
        else:
             num_sche_requests = min(num_sche_requests, ELEVATOR_COUNT)
        num_passenger_requests = max(1, min(num_passenger_requests, 100))
        num_passenger_requests = min(num_passenger_requests, MAX_TOTAL_REQUESTS_MUTUAL - num_sche_requests)
    else:
        num_passenger_requests = max(1, min(num_passenger_requests, 100))
        num_sche_requests = min(num_sche_requests, MAX_SCHE_REQUESTS_PUBLIC)

    person_ids = random.sample(range(1, 10001 + num_passenger_requests), num_passenger_requests)
    person_id_index = 0
    sche_request_counts = {i: 0 for i in range(1, ELEVATOR_COUNT + 1)}
    sche_requests_generated = 0
    passenger_reqs_generated = 0
    last_sche_time_for_elevator = {i: 0.0 for i in range(1, ELEVATOR_COUNT + 1)}

    ph1_end = max_time * 0.15; ph2_end = max_time * 0.50
    ph3_end = max_time * 0.75; ph4_end = max_time
    ratios = [0.10, 0.40, 0.20, 0.30]
    phase_defs = [ (0.0, ph1_end, ratios[0], 'sparse_sche'), (ph1_end, ph2_end, ratios[1], 'dense_sche'),
                   (ph2_end, ph3_end, ratios[2], 'boundary_sche'), (ph3_end, ph4_end, ratios[3], 'priority_sche') ]

    current_time = 1.0; last_generated_time = 0.0
    phase_requests_temp = []
    remaining_p = num_passenger_requests; remaining_s = num_sche_requests

    for i, (phase_start, phase_end, req_ratio, phase_type) in enumerate(phase_defs):
        phase_time_span = phase_end - phase_start
        if i == len(phase_defs) - 1:
            num_passenger_target = remaining_p; num_sche_target = remaining_s
        else:
            num_passenger_target = min(int(num_passenger_requests * req_ratio), remaining_p)
            num_sche_target = min(int(num_sche_requests * req_ratio), remaining_s)

        timestamps_passenger = sorted([phase_start + random.uniform(0, phase_time_span) for _ in range(num_passenger_target)])
        timestamps_sche = sorted([phase_start + random.uniform(0, phase_time_span) for _ in range(num_sche_target)])
        all_timestamps_with_type = sorted([(t, 'passenger') for t in timestamps_passenger] + [(t, 'sche') for t in timestamps_sche])

        for ts, req_type in all_timestamps_with_type:
            if passenger_reqs_generated >= num_passenger_requests and req_type == 'passenger': continue
            if sche_requests_generated >= num_sche_requests and req_type == 'sche': continue

            request_time = max(current_time, ts) + random.uniform(0.001, 0.01)
            request_time = round(request_time, 3)
            request_time = min(request_time, max_time - 0.001)
            request_time = max(request_time, last_generated_time + 0.001)
            request_time = round(request_time, 3)
            if request_time >= max_time: continue

            current_time = request_time; last_generated_time = request_time
            request_str = None

            if req_type == 'passenger' and passenger_reqs_generated < num_passenger_requests:
                if person_id_index >= len(person_ids): break
                pid = person_ids[person_id_index]; person_id_index += 1
                from_floor, to_floor, priority = -99, -99, -1
                if phase_type == 'sparse_sche': from_floor=random.choice(VALID_FLOORS); to_floor=random.choice(list(set(VALID_FLOORS)-{from_floor})); priority=random.randint(1, 40)
                elif phase_type == 'dense_sche': from_floor=random.choice(VALID_FLOORS); to_floor=random.choice(list(set(VALID_FLOORS)-{from_floor})); priority=random.randint(30, 70)
                elif phase_type == 'boundary_sche':
                    case_type = random.choice(['extreme_dist', 'cross_zero', 'short_dist'])
                    if case_type == 'extreme_dist': from_floor, to_floor = (FLOOR_MAX, FLOOR_MIN) if random.random()<0.5 else (FLOOR_MIN, FLOOR_MAX); priority = random.randint(40,80)
                    elif case_type == 'cross_zero': from_floor, to_floor = (random.choice([1,2]), random.choice([-1,-2])) if random.random()<0.5 else (random.choice([-1,-2]), random.choice([1,2])); priority = random.randint(20,60)
                    elif case_type == 'short_dist':
                         from_floor=random.choice(VALID_FLOORS); adj = []
                         if from_floor > FLOOR_MIN and from_floor != 1: adj.append(from_floor-1)
                         if from_floor < FLOOR_MAX and from_floor != -1: adj.append(from_floor+1)
                         if from_floor == 1: adj = [2, -1];
                         elif from_floor == -1: adj = [-2, 1]
                         if not adj:
                             if from_floor == FLOOR_MAX: adj = [FLOOR_MAX - 1]
                             elif from_floor == FLOOR_MIN: adj = [FLOOR_MIN + 1]
                             else: adj = [from_floor + random.choice([-1, 1])] if FLOOR_MIN < from_floor < FLOOR_MAX and from_floor not in [0, 1, -1] else [2 if from_floor == 1 else -2]
                         to_floor=random.choice(adj); priority = random.randint(1,30)
                elif phase_type == 'priority_sche':
                     from_floor=random.choice(VALID_FLOORS); to_floor=random.choice(list(set(VALID_FLOORS)-{from_floor}))
                     priority = 1 if random.random() < 0.3 else random.randint(80, 100)

                while from_floor == to_floor or from_floor not in VALID_FLOORS or to_floor not in VALID_FLOORS:
                     from_floor = random.choice(VALID_FLOORS); possible_tos = list(set(VALID_FLOORS) - {from_floor})
                     if not possible_tos: from_floor = 1; possible_tos = list(set(VALID_FLOORS) - {from_floor})
                     to_floor = random.choice(possible_tos)
                request_str = (f"[{request_time:.1f}]{pid}-PRI-{priority}-FROM-{floor_to_str(from_floor)}-TO-{floor_to_str(to_floor)}")
                if request_str: passenger_reqs_generated += 1

            elif req_type == 'sche' and sche_requests_generated < num_sche_requests:
                possible_elevators = list(range(1, ELEVATOR_COUNT + 1))
                valid_schedule_elevators = []
                for eid in possible_elevators:
                    if is_mutual_test and sche_request_counts[eid] >= MAX_SCHE_PER_ELEVATOR_MUTUAL: continue
                    if eid not in last_sche_time_for_elevator:
                        print(f"CRITICAL ERROR: Invalid eid {eid} accessed in last_sche_time_for_elevator!")
                        continue
                    if request_time < last_sche_time_for_elevator[eid] + MIN_SCHE_INTERVAL_ESTIMATE: continue
                    valid_schedule_elevators.append(eid)

                if not valid_schedule_elevators: continue

                elevator_id = random.choice(valid_schedule_elevators)
                target_floor = random.choice(SCHE_TARGET_FLOORS)
                speed = random.choice(SCHE_SPEEDS_CORRECT)
                request_str = (f"[{request_time:.1f}]SCHE-{elevator_id}-{speed:.1f}-{floor_to_str(target_floor)}")
                if request_str:
                    sche_request_counts[elevator_id] += 1
                    sche_requests_generated += 1
                    last_sche_time_for_elevator[elevator_id] = request_time

            if request_str:
                phase_requests_temp.append((request_time, request_str))

        remaining_p = num_passenger_requests - passenger_reqs_generated
        remaining_s = num_sche_requests - sche_requests_generated
        if remaining_p <= 0 and remaining_s <= 0: break

    phase_requests_temp.sort(key=lambda x: x[0])
    final_requests_output = []; last_output_time_numeric = 0.0
    actual_passenger_reqs = 0; actual_sche_reqs = 0

    for req_time_float, req_str_full in phase_requests_temp:
        is_sche = req_str_full.split(']')[1].startswith('SCHE')
        if is_sche: actual_sche_reqs += 1
        else: actual_passenger_reqs += 1
        output_time_float = round(req_time_float, 1)
        if output_time_float < last_output_time_numeric: output_time_float = last_output_time_numeric
        if output_time_float >= max_time: continue

        reconstructed_str = None
        match_passenger = re.match(r"\[.*?\](\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)", req_str_full)
        if match_passenger and len(match_passenger.groups()) == 4:
            pid, pri, from_s, to_s = match_passenger.groups()
            reconstructed_str = (f"[{output_time_float:.1f}]{pid}-PRI-{pri}-FROM-{from_s}-TO-{to_s}")
        else:
            match_sche = re.match(r"\[.*?\]SCHE-(\d+)-(\d+\.\d+)-([BF]\d+)", req_str_full)
            if match_sche and len(match_sche.groups()) == 3:
                el_id, spd_s, floor_s = match_sche.groups()
                try:
                    speed_float = float(spd_s)
                    reconstructed_str = f"[{output_time_float:.1f}]SCHE-{el_id}-{speed_float:.1f}-{floor_s}"
                except ValueError: print(f"Warning: Cannot parse speed '{spd_s}' in SCHE: {req_str_full}")

        if reconstructed_str:
             final_requests_output.append(reconstructed_str)
             last_output_time_numeric = output_time_float

    final_requests_count = len(final_requests_output)

    try:
        with open(filename, "w", encoding='utf-8') as f:
            for req_str in final_requests_output: f.write(req_str + "\n")
        print(f"Generated {final_requests_count} requests ({actual_passenger_reqs} passenger, {actual_sche_reqs} SCHE actual) into {filename} (mode: {'mutual' if is_mutual_test else 'public'}, max_time: {max_time:.1f}s)")
        return True
    except IOError as e:
        print(f"Error writing to {filename}: {e}")
        return False

if __name__ == '__main__':
    print("Generating data for HW6 (mutual test settings by default)...")
    if generate_requests_phased_hw6(is_mutual_test=True, filename="stdin.txt"):
        print("Generated stdin.txt for HW6 (mutual test).")
    else:
        print("Failed to generate stdin.txt for HW6.")