import random
import time
import math
import bisect

VALID_FLOORS = list(range(-4, 0)) + list(range(1, 8))

def floor_to_str(floor):
    if floor < 0: return f"B{-floor}"
    else: return f"F{floor}"

def generate_requests_phased(num_requests=80, max_time=50.0, filename="stdin.txt", elevator_count=6, max_req_per_elevator=30):
    if not 1 <= num_requests <= 100:

        num_requests = max(1, min(num_requests, 100))

    requests_data = []
    max_possible_twins = num_requests // 5
    total_ids_needed = num_requests + max_possible_twins

    person_ids = random.sample(range(1, 10001 + max_possible_twins * 2), total_ids_needed)
    elevator_request_counts = {i: 0 for i in range(1, elevator_count + 1)}

    phases = [
        (10.0, int(num_requests * 0.10), 0, True),
        (25.0, int(num_requests * 0.40), 2, True),
        (35.0, int(num_requests * 0.10), 1, False),
        (max_time, int(num_requests * 0.40), 2, True),
    ]
    total_assigned = sum(p[1] for p in phases)
    if total_assigned < num_requests:
        phases[-1] = (phases[-1][0], phases[-1][1] + (num_requests - total_assigned), phases[-1][2], phases[-1][3])
    elif total_assigned > num_requests:
         diff = total_assigned - num_requests
         phases[-1] = (phases[-1][0], max(0, phases[-1][1] - diff), phases[-1][2], phases[-1][3])


    current_time = 1.0
    last_phase_end_time = 0.0
    person_id_index = 0
    request_counter = 0

    for phase_end_time, phase_num_reqs, intensity, inject_boundaries in phases:
        phase_start_time = last_phase_end_time
        time_span = phase_end_time - phase_start_time


        timestamps = []
        if phase_num_reqs > 0:

            if intensity == 2:
                skew_factor = 0.3
                for _ in range(phase_num_reqs): ts = phase_start_time + time_span * (random.random() ** (1.0 / skew_factor)); timestamps.append(ts)
                timestamps.sort()
            elif intensity == 1: timestamps = sorted([phase_start_time + random.uniform(0, time_span) for _ in range(phase_num_reqs)])
            else:
                 base_timestamps = sorted([random.uniform(0, time_span) for _ in range(phase_num_reqs)])
                 avg_gap = time_span / (phase_num_reqs + 1) if phase_num_reqs > 0 else time_span
                 for i in range(phase_num_reqs): timestamps.append(phase_start_time + base_timestamps[i] * 0.8 + avg_gap * (i + 1) * 0.2)
                 timestamps.sort()

        num_boundaries_injected = 0
        if inject_boundaries and phase_num_reqs > 3:
            boundary_indices = random.sample(range(phase_num_reqs), k=min(3, phase_num_reqs // 5))
            num_boundaries_injected = len(boundary_indices)


        boundary_case_counter = 0
        for i in range(phase_num_reqs):
            if person_id_index >= len(person_ids):

                break

            request_time = max(current_time, timestamps[i])
            request_time += random.uniform(0.001, 0.01)
            request_time = round(request_time, 3)
            request_time = min(request_time, max_time - 0.1)
            current_time = request_time

            from_floor, to_floor, priority = -99, -99, -1
            is_boundary = (boundary_case_counter < num_boundaries_injected and i in boundary_indices)
            add_twin = False

            if is_boundary:
                boundary_case_counter += 1
                case_type = random.choice(['extreme_dist', 'cross_zero', 'priority_diff', 'short_dist'])

                if case_type == 'extreme_dist': from_floor, to_floor = (7, -4) if random.random()<0.5 else (-4, 7); priority = random.randint(40,80)
                elif case_type == 'cross_zero': from_floor, to_floor = (random.choice([1,2]), random.choice([-1,-2])) if random.random()<0.5 else (random.choice([-1,-2]), random.choice([1,2])); priority = random.randint(20,60)
                elif case_type == 'priority_diff': from_floor=random.choice([1,-1,2,3,4]); to_floor=random.choice(list(set(VALID_FLOORS)-{from_floor})); priority=1; add_twin=True
                elif case_type == 'short_dist':
                     from_floor=random.choice(VALID_FLOORS)
                     if from_floor==7: to_floor=6
                     elif from_floor==-4: to_floor=-3
                     elif from_floor==1: to_floor=random.choice([2,-1])
                     elif from_floor==-1: to_floor=random.choice([1,-2])
                     else: to_floor=from_floor+random.choice([-1,1])
                     priority = random.randint(1,30)

            else:
                 if intensity == 2: from_floor, to_floor, priority = (random.choice([-2,-1,1,2]), random.choice([5,6,7,4]), random.randint(60,100)) if random.random()<0.5 else (random.choice([4,5,6,7,-3,-4]), random.choice([1,2,-1,-2]), random.randint(60,100))
                 elif intensity == 1: from_floor=random.choice(VALID_FLOORS); to_floor=random.choice(list(set(VALID_FLOORS)-{from_floor})); priority=random.randint(20,80)
                 else: from_floor=random.choice(VALID_FLOORS); to_floor=random.choice(list(set(VALID_FLOORS)-{from_floor})); priority=random.randint(1,50)

            while from_floor == to_floor or from_floor == 0 or to_floor == 0 or from_floor == -99:
                 from_floor = random.choice(VALID_FLOORS); to_floor = random.choice(list(set(VALID_FLOORS) - {from_floor}))

            possible_elevators = [e for e, count in elevator_request_counts.items() if count < max_req_per_elevator]
            if not possible_elevators: continue
            elevator_id = random.choice(possible_elevators)
            elevator_request_counts[elevator_id] += 1

            pid = person_ids[person_id_index]
            request_str = (f"[{request_time:.1f}]{pid}-PRI-{priority}"
                           f"-FROM-{floor_to_str(from_floor)}-TO-{floor_to_str(to_floor)}"
                           f"-BY-{elevator_id}")
            requests_data.append((request_time, request_str))
            person_id_index += 1
            request_counter += 1

            if is_boundary and case_type == 'priority_diff' and add_twin:
                 if person_id_index < len(person_ids) and request_counter < total_ids_needed:
                     twin_time = round(request_time + random.uniform(0.01, 0.05), 3); twin_time = min(twin_time, max_time - 0.1)
                     twin_priority = 100; twin_elevator_id = -1

                     if elevator_request_counts[elevator_id] < max_req_per_elevator: twin_elevator_id = elevator_id; elevator_request_counts[elevator_id] += 1
                     else:
                          possible_tw_elevators = [e for e, count in elevator_request_counts.items() if count < max_req_per_elevator]
                          if not possible_tw_elevators: continue
                          twin_elevator_id = random.choice(possible_tw_elevators); elevator_request_counts[twin_elevator_id] += 1

                     twin_pid = person_ids[person_id_index]
                     twin_request_str = (f"[{twin_time:.1f}]{twin_pid}-PRI-{twin_priority}"
                                        f"-FROM-{floor_to_str(from_floor)}-TO-{floor_to_str(to_floor)}"
                                        f"-BY-{twin_elevator_id}")
                     bisect.insort_left(requests_data, (twin_time, twin_request_str))
                     person_id_index += 1
                     request_counter += 1

                 add_twin = False

        last_phase_end_time = phase_end_time
        if person_id_index >= len(person_ids): break

    requests_data.sort(key=lambda x: x[0])

    final_requests = [req_str for _, req_str in requests_data]
    if len(final_requests) > num_requests:

        final_requests = final_requests[:num_requests]


    try:
        with open(filename, "w") as f:
            for req_str in final_requests:
                f.write(req_str + "\n")
        # ======> 保留这一行，用于 run_test.py 的输出 <======
        print(f"Generated {len(final_requests)} requests into {filename}")
        return True
    except IOError as e:
        print(f"Error writing to {filename}: {e}")
        return False

if __name__ == '__main__':
    # 保持这里的调用不变，但函数内部的 print 已被注释
    generate_requests_phased(num_requests=80, filename="stdin.txt")
    print("Generated stdin.txt with phased data (debug prints suppressed).") # 可以修改这里的提示信息