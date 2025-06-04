# validator.py
import re
import math
from collections import defaultdict, deque

# --- Constants ---
MOVE_TIME = 0.4
DOOR_TIME = 0.4
EPSILON = 0.001 # Tolerance for float comparisons
MAX_CAPACITY = 6 # <--- 电梯最大容量常量
FLOOR_MIN = -4
FLOOR_MAX = 7
VALID_FLOORS_SET = set(range(-4, 0)) | set(range(1, 8))

# --- State Enums/Constants ---
DOOR_CLOSED = 0
DOOR_OPEN = 1
# (可选的中间状态，当前未使用)
# DOOR_OPENING = 2
# DOOR_CLOSING = 3

PASSENGER_WAITING = 0
PASSENGER_INSIDE = 1
PASSENGER_ARRIVED = 2

# --- Helper Functions ---
def str_to_floor(floor_str):
    """Converts floor string (e.g., B1, F3) to integer."""
    if not floor_str: return None
    prefix = floor_str[0]
    try:
        num = int(floor_str[1:])
        if prefix == 'B':
            return -num
        elif prefix == 'F':
            return num
        else:
            return None # Invalid format
    except (ValueError, IndexError):
        return None

def floor_to_str(floor):
    """Converts integer floor to string format (e.g., -1 -> B1, 3 -> F3)."""
    if floor is None: return "None" # Handle possible None values
    try:
        floor_int = int(floor) # Ensure it's an integer
        if floor_int < 0:
            return f"B{-floor_int}"
        elif floor_int > 0:
            return f"F{floor_int}"
        else:
            return "InvalidFloor(0)" # Floor 0 should not appear
    except (ValueError, TypeError):
        return f"InvalidFloor({floor})" # Handle non-numeric input

# --- State Classes ---
class PassengerState:
    def __init__(self, id, priority, from_fl, to_fl, assigned_el, req_time):
        self.id = id
        self.priority = priority
        self.from_floor = from_fl
        self.to_floor = to_fl
        self.assigned_elevator = assigned_el
        self.request_time = req_time
        self.finish_time = -1.0
        self.current_location = from_fl # Initial location
        self.state = PASSENGER_WAITING
        self.current_elevator = -1 # Elevator ID if inside

    def __repr__(self):
        loc_str = floor_to_str(self.current_location) if self.state != PASSENGER_INSIDE else "Inside"
        state_map = {PASSENGER_WAITING: "WAITING", PASSENGER_INSIDE: "INSIDE", PASSENGER_ARRIVED: "ARRIVED"}
        el_str = f" el={self.current_elevator}" if self.state == PASSENGER_INSIDE else ""
        return f"P(id={self.id}, loc={loc_str}, st={state_map.get(self.state, 'UNKNOWN')}{el_str})"

class ElevatorState:
    def __init__(self, id):
        self.id = id
        self.current_floor = 1 # Start at F1
        self.door_state = DOOR_CLOSED
        self.passengers = set() # Set of passenger IDs inside
        self.last_event_time = 0.0
        self.last_action_finish_time = 0.0 # Tracks when movement/door actions *complete*

    @property
    def passenger_count(self):
        return len(self.passengers)

    def __repr__(self):
        door_map = {DOOR_CLOSED: "CLOSED", DOOR_OPEN: "OPEN"}
        fl_str = floor_to_str(self.current_floor)
        return (f"E(id={self.id}, fl={fl_str}, door={door_map.get(self.door_state,'UNKNOWN')}, "
                f"num={self.passenger_count}, last_t={self.last_event_time:.4f})")

# --- Validator Class ---
class OutputValidator:
    def __init__(self, stdin_file):
        self.errors = []
        self.events = []
        self.passengers = {}
        self.elevators = {}
        self.parse_stdin(stdin_file)
        for i in range(1, 7):
            self.elevators[i] = ElevatorState(id=i)
        self.last_global_time = 0.0
        self.power_arrive = 0
        self.power_open = 0
        self.power_close = 0
        self.total_runtime = 0.0

    def add_error(self, message, timestamp=None):
        ts_str = f" (at time ~{timestamp:.4f})" if timestamp is not None else ""
        full_message = f"Validation Error: {message}{ts_str}"
        if not self.errors or self.errors[-1] != full_message:
             self.errors.append(full_message)

    def parse_stdin(self, filename):
        # ... (保持不变) ...
        try:
            with open(filename, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line: continue
                    match = re.match(r"\[(\d+\.\d+)\](\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)-BY-(\d+)", line)
                    if not match:
                        self.add_error(f"Invalid stdin format on line {line_num}: {line}")
                        continue

                    t, p_id, pri, from_s, to_s, el_id = match.groups()
                    timestamp = float(t)
                    person_id = int(p_id)
                    priority = int(pri)
                    from_floor = str_to_floor(from_s)
                    to_floor = str_to_floor(to_s)
                    elevator_id = int(el_id)

                    if from_floor is None or to_floor is None or from_floor not in VALID_FLOORS_SET \
                       or to_floor not in VALID_FLOORS_SET or from_floor == to_floor \
                       or elevator_id < 1 or elevator_id > 6 or priority < 1 or person_id < 1:
                         self.add_error(f"Invalid data in stdin request on line {line_num}: {line}")
                         continue

                    if person_id in self.passengers:
                         self.add_error(f"Duplicate Person ID {person_id} in stdin on line {line_num}")
                         continue

                    self.passengers[person_id] = PassengerState(
                        person_id, priority, from_floor, to_floor, elevator_id, timestamp
                    )
        except FileNotFoundError:
            self.add_error(f"Stdin file not found: {filename}")
        except Exception as e:
             self.add_error(f"Error reading stdin file {filename}: {e}")


    def parse_output_line(self, line):
        # ... (保持不变, 使用上一版本修正后的代码) ...
        line = line.strip()
        if not line: return None
        timestamp_pattern = r"\[\s*(\d+\.\d+)\s*\]" # Allows space, multiple decimal places
        match_ts_event = re.match(timestamp_pattern + "(.*)", line)
        if not match_ts_event:
            self.add_error(f"Output line missing or invalid timestamp format: {line}")
            return None

        timestamp_str = match_ts_event.group(1)
        event_content = match_ts_event.group(2).strip()
        current_time = float(timestamp_str)

        if current_time < self.last_global_time - EPSILON:
             self.add_error(f"Timestamp non-decreasing violation: {current_time:.4f} < {self.last_global_time:.4f}", current_time)
        self.last_global_time = max(self.last_global_time, current_time)
        self.total_runtime = self.last_global_time

        patterns_simple = {
            "ARRIVE": r"ARRIVE-([BF]\d+)-(\d+)",
            "OPEN":   r"OPEN-([BF]\d+)-(\d+)",
            "CLOSE":  r"CLOSE-([BF]\d+)-(\d+)",
            "IN":     r"IN-(\d+)-([BF]\d+)-(\d+)",
            "OUT":    r"OUT-(\d+)-([BF]\d+)-(\d+)",
        }

        for type, pattern in patterns_simple.items():
            match = re.match(pattern, event_content)
            if match:
                groups = match.groups()
                try:
                    if type in ["ARRIVE", "OPEN", "CLOSE"]:
                        floor_str = groups[0]
                        floor = str_to_floor(floor_str)
                        elevator_id = int(groups[1])
                        if floor is None or elevator_id not in self.elevators:
                            self.add_error(f"Invalid floor/elevator in {type}: {line} (FloorStr: {floor_str}, ElId: {elevator_id})", current_time)
                            return None
                        return {"type": type, "time": current_time, "floor": floor, "elevator_id": elevator_id}
                    elif type in ["IN", "OUT"]:
                        person_id = int(groups[0])
                        floor_str = groups[1]
                        floor = str_to_floor(floor_str)
                        elevator_id = int(groups[2])
                        if person_id not in self.passengers:
                             self.add_error(f"Unknown Person ID {person_id} in {type}: {line}", current_time)
                             return None
                        if floor is None or elevator_id not in self.elevators:
                             self.add_error(f"Invalid floor/elevator in {type}: {line} (FloorStr: {floor_str}, PId: {person_id}, ElId: {elevator_id})", current_time)
                             return None
                        return {"type": type, "time": current_time, "person_id": person_id, "floor": floor, "elevator_id": elevator_id}
                except (ValueError, IndexError) as e:
                     self.add_error(f"Error parsing arguments for {type} in line: {line} - {e}", current_time)
                     return None

        self.add_error(f"Unrecognized event content after timestamp: {event_content} (Original line: {line})", current_time)
        return None

    def validate_event(self, event):
        """Applies rules based on event type and updates state if valid."""
        if event is None or "type" not in event or "time" not in event or "elevator_id" not in event:
            self.add_error(f"Internal Error: Invalid event structure passed to validate_event: {event}")
            return False

        ev_type = event["type"]
        ev_time = event["time"]
        el_id = event["elevator_id"]

        if el_id not in self.elevators:
             self.add_error(f"Event refers to non-existent Elevator ID {el_id}: {event}", ev_time)
             return False

        elevator = self.elevators[el_id]
        elevator.last_event_time = ev_time # 更新最后事件时间戳

        # 使用 door_map 辅助打印门状态
        door_map = {DOOR_CLOSED: "CLOSED", DOOR_OPEN: "OPEN"}
        current_door_state_str = door_map.get(elevator.door_state, 'UNKNOWN')

        try:
            if ev_type == "ARRIVE":
                self.power_arrive += 1
                floor = event["floor"]
                # 检查：移动时门必须关闭
                if elevator.door_state == DOOR_OPEN:
                    self.add_error(f"Elevator {el_id} ARRIVE at {floor_to_str(floor)} while doors were OPEN", ev_time)
                    # 即使违规，也更新状态以反映日志

                # --- 时间和楼层检查 (保持不变) ---
                expected_arrival_time = elevator.last_action_finish_time + MOVE_TIME
                timing_epsilon = EPSILON * 10
                if ev_time < expected_arrival_time - timing_epsilon:
                     self.add_error(f"Elevator {el_id} ARRIVE at {floor_to_str(floor)} too fast. "
                                    f"Time: {ev_time:.4f}, Expected >= {expected_arrival_time:.4f} (Last finish: {elevator.last_action_finish_time:.4f})", ev_time)
                floor_diff = abs(floor - elevator.current_floor)
                is_crossing_zero = (elevator.current_floor == 1 and floor == -1) or \
                                   (elevator.current_floor == -1 and floor == 1)
                if floor not in VALID_FLOORS_SET:
                     self.add_error(f"Elevator {el_id} ARRIVE at invalid floor {floor_to_str(floor)}", ev_time)
                elif floor_diff != 1 and not is_crossing_zero:
                     if floor != elevator.current_floor:
                          self.add_error(f"Elevator {el_id} invalid move: {floor_to_str(elevator.current_floor)} -> {floor_to_str(floor)}", ev_time)

                # --- 状态更新 ---
                elevator.current_floor = floor
                elevator.last_action_finish_time = ev_time
                return True

            elif ev_type == "OPEN":
                self.power_open += 1
                floor = event["floor"]
                # ======> 新增/修改检查：只有在关门状态下才能开门 <======
                if elevator.door_state != DOOR_CLOSED:
                     self.add_error(f"Elevator {el_id} tried to OPEN but was not in CLOSED state (current state: {current_door_state_str})", ev_time)
                     # 即使违规，也根据日志更新状态？或者阻止状态更新？先记录错误并更新

                # --- 其他检查 (保持不变) ---
                if floor != elevator.current_floor:
                    self.add_error(f"Elevator {el_id} OPEN at wrong floor {floor_to_str(floor)}, current is {floor_to_str(elevator.current_floor)}", ev_time)
                # (这个检查现在被上面的 ! = DOOR_CLOSED 包含了)
                # if elevator.door_state == DOOR_OPEN:
                #      self.add_error(f"Elevator {el_id} OPEN called while already OPEN", ev_time)
                timing_epsilon = EPSILON * 10
                if ev_time < elevator.last_action_finish_time - timing_epsilon:
                     self.add_error(f"Elevator {el_id} OPEN too early. Time: {ev_time:.4f}, "
                                    f"Previous action finished at {elevator.last_action_finish_time:.4f}", ev_time)

                # --- 状态更新 ---
                elevator.door_state = DOOR_OPEN
                elevator.last_action_finish_time = ev_time
                return True

            elif ev_type == "CLOSE":
                self.power_close += 1
                floor = event["floor"]
                # ======> 确认检查：只有在开门状态下才能关门 <======
                if elevator.door_state != DOOR_OPEN:
                     self.add_error(f"Elevator {el_id} tried to CLOSE but was not in OPEN state (current state: {current_door_state_str})", ev_time)
                     # 即使违规，也根据日志更新状态

                # --- 其他检查 (保持不变) ---
                if floor != elevator.current_floor:
                    self.add_error(f"Elevator {el_id} CLOSE at wrong floor {floor_to_str(floor)}, current is {floor_to_str(elevator.current_floor)}", ev_time)

                open_start_time = -1.0
                for prev_event in reversed(self.events):
                    if prev_event["type"] == "OPEN" and prev_event["elevator_id"] == el_id and prev_event["floor"] == floor:
                        open_start_time = prev_event["time"]
                        break
                if open_start_time < 0:
                    self.add_error(f"Could not find preceding valid OPEN event for Elevator {el_id} at {floor_to_str(floor)} to check CLOSE duration", ev_time)
                    duration = -1
                else:
                    duration = ev_time - open_start_time

                timing_epsilon = EPSILON * 10
                if duration >= 0 and duration < DOOR_TIME - timing_epsilon:
                     self.add_error(f"Elevator {el_id} door open duration too short: {duration:.4f}s (< {DOOR_TIME}s), Open time: {open_start_time:.4f}, Close time: {ev_time:.4f}", ev_time)

                # --- 状态更新 ---
                elevator.door_state = DOOR_CLOSED
                elevator.last_action_finish_time = ev_time
                return True

            elif ev_type == "IN":
                floor = event["floor"]
                person_id = event["person_id"]
                if person_id not in self.passengers:
                     self.add_error(f"Internal Error: Passenger {person_id} not found during IN event processing", ev_time)
                     return True

                passenger = self.passengers[person_id]

                # ======> 确认检查：乘客只有在开门状态下才能进电梯 <======
                if elevator.door_state != DOOR_OPEN:
                    self.add_error(f"Passenger {person_id} tried to IN Elevator {el_id} while doors were not OPEN (state: {current_door_state_str})", ev_time)

                # ======> 新增检查：电梯内最多只能有6个人 (实时检测) <======
                if elevator.passenger_count >= MAX_CAPACITY:
                     self.add_error(f"Elevator {el_id} exceeds capacity ({MAX_CAPACITY}) trying to let IN {person_id} ({elevator.passenger_count} already inside)", ev_time)
                     # 注意：即使超载，也可能需要根据日志更新状态，取决于严格程度
                     # 这里我们先记录错误，然后继续更新状态以反映日志

                # --- 其他检查 (保持不变) ---
                if floor != elevator.current_floor:
                    self.add_error(f"Passenger {person_id} IN Elevator {el_id} at wrong floor {floor_to_str(floor)}, elevator is at {floor_to_str(elevator.current_floor)}", ev_time)
                if passenger.state != PASSENGER_WAITING:
                    state_map = {PASSENGER_WAITING: "WAITING", PASSENGER_INSIDE: "INSIDE", PASSENGER_ARRIVED: "ARRIVED"}
                    self.add_error(f"Passenger {person_id} IN Elevator {el_id} but was not WAITING (state={state_map.get(passenger.state, 'UNKNOWN')})", ev_time)
                elif floor != passenger.current_location: # 仅当乘客是等待状态时检查位置
                     self.add_error(f"Passenger {person_id} IN Elevator {el_id} at floor {floor_to_str(floor)}, but passenger waiting location was {floor_to_str(passenger.current_location)}", ev_time)
                if el_id != passenger.assigned_elevator:
                     self.add_error(f"Passenger {person_id} IN wrong Elevator {el_id}, assigned to {passenger.assigned_elevator}", ev_time)

                # --- 状态更新 ---
                # 即使有错误，也根据日志更新状态，因为日志声称发生了这件事
                passenger.state = PASSENGER_INSIDE
                passenger.current_elevator = el_id
                passenger.current_location = -999
                # 只有在未超载且乘客不在电梯内时才添加 (防止因状态错误重复添加)
                # 但如果日志说IN了，即使超载，也可能需要模拟加入状态？这取决于验证的严格性
                # 方案：记录错误，但总是尝试根据日志更新（如果验证器目标是忠实反映日志并指出矛盾）
                if person_id not in elevator.passengers:
                     elevator.passengers.add(person_id)
                # else: # 如果乘客已在电梯内但又IN，这也是个错误
                #     self.add_error(f"Passenger {person_id} IN Elevator {el_id} but was already recorded as inside.", ev_time)

                return True

            elif ev_type == "OUT":
                floor = event["floor"]
                person_id = event["person_id"]
                if person_id not in self.passengers:
                     self.add_error(f"Internal Error: Passenger {person_id} not found during OUT event processing", ev_time)
                     return True

                passenger = self.passengers[person_id]

                # ======> 确认检查：乘客只有在开门状态下才能出电梯 <======
                if elevator.door_state != DOOR_OPEN:
                    self.add_error(f"Passenger {person_id} tried to OUT Elevator {el_id} while doors were not OPEN (state: {current_door_state_str})", ev_time)

                # --- 其他检查 (保持不变) ---
                if floor != elevator.current_floor:
                    self.add_error(f"Passenger {person_id} OUT Elevator {el_id} at wrong floor {floor_to_str(floor)}, elevator is at {floor_to_str(elevator.current_floor)}", ev_time)
                if passenger.state != PASSENGER_INSIDE or passenger.current_elevator != el_id:
                     self.add_error(f"Passenger {person_id} OUT Elevator {el_id} but was not recorded as INSIDE this elevator (state={passenger.state}, current_el={passenger.current_elevator})", ev_time)
                     # 如果乘客状态不对，后续移除可能会失败或不准确

                # --- 状态更新 ---
                passenger.current_elevator = -1
                passenger.current_location = floor
                if person_id in elevator.passengers:
                     elevator.passengers.remove(person_id)
                else:
                      # 只有在乘客状态正确时，这才是状态不一致错误
                      if passenger.state == PASSENGER_INSIDE and passenger.current_elevator == el_id:
                           self.add_error(f"State Inconsistency: Passenger {person_id} OUT Elevator {el_id}, but not found in elevator's passenger set.", ev_time)

                if floor == passenger.to_floor:
                    passenger.state = PASSENGER_ARRIVED
                    passenger.finish_time = ev_time
                else:
                    # 如果在中途下车，状态变为在当前楼层等待
                    passenger.state = PASSENGER_WAITING
                return True

        except Exception as e:
             self.add_error(f"Internal validation error processing event {event}: {e}", ev_time)
             # 打印更详细的 traceback 帮助调试验证器本身
             import traceback
             traceback.print_exc()
             return False

        self.add_error(f"Unknown event type '{ev_type}' in validate_event", ev_time)
        return False


    def validate_output(self, output_lines):
        # ... (这个方法主体逻辑保持不变, 依赖 validate_event 进行检查) ...
        # --- Reset state before validation ---
        self.errors = []
        self.events = []
        self.last_global_time = 0.0
        self.power_arrive = 0
        self.power_open = 0
        self.power_close = 0
        self.total_runtime = 0.0

        for el in self.elevators.values():
            el.current_floor = 1
            el.door_state = DOOR_CLOSED
            el.passengers = set()
            el.last_event_time = 0.0
            el.last_action_finish_time = 0.0

        if not self.passengers:
             if not output_lines:
                 print("Warning: No requests in stdin and no output generated.")
                 return True
             else:
                  self.add_error("No requests loaded from stdin, but output was generated.")
        else:
            for p in self.passengers.values():
                p.finish_time = -1.0
                p.current_location = p.from_floor
                p.state = PASSENGER_WAITING
                p.current_elevator = -1

        if self.errors:
            print("Errors found during state initialization/stdin parsing:")
            for err in self.errors: print(f"  - {err}")
            return False

        parsing_errors = []
        parsed_events_raw = []
        initial_error_count = len(self.errors) # Track errors before parsing
        for line in output_lines:
            event = self.parse_output_line(line)
            # Collect only new errors added by parser
            parsing_errors.extend(self.errors[initial_error_count + len(parsing_errors):])
            if event:
                parsed_events_raw.append(event)

        if parsing_errors:
             print("Errors found during output parsing:")
             for err in parsing_errors: print(f"  - {err}")


        validation_error_count_before = len(self.errors)
        for event in parsed_events_raw:
             if self.validate_event(event):
                  # Only add successfully processed (logic-wise) events to history for state tracking
                  self.events.append(event)
             # validate_event adds errors to self.errors directly

        # --- Final State Checks ---
        print("\n--- Final State Check ---")
        final_check_errors = []
        all_passengers_arrived = True
        if not self.passengers:
             print("Passenger Check: SKIPPED (No requests loaded)")
             all_passengers_arrived = True
        else:
            for pid, p in self.passengers.items():
                if p.state != PASSENGER_ARRIVED:
                    error_msg = f"Passenger {pid} did not reach destination {floor_to_str(p.to_floor)}. Final state: {p}"
                    final_check_errors.append(error_msg)
                    all_passengers_arrived = False
                elif p.current_location != p.to_floor:
                     error_msg = f"Passenger {pid} state is ARRIVED but final location {floor_to_str(p.current_location)} != destination {floor_to_str(p.to_floor)}"
                     final_check_errors.append(error_msg)
                     all_passengers_arrived = False

            if all_passengers_arrived:
                print("Passenger Check: OK - All passengers reached their destinations.")
            else:
                 print("Passenger Check: FAILED")


        elevators_ok = True
        for eid, el in self.elevators.items():
            if el.passenger_count > 0:
                # Format passenger IDs nicely if possible
                p_ids = ", ".join(map(str, sorted(list(el.passengers))))
                error_msg = f"Elevator {eid} finished with {el.passenger_count} passengers inside: [{p_ids}]"
                final_check_errors.append(error_msg)
                elevators_ok = False
            if el.door_state != DOOR_CLOSED:
                state_str = "OPEN" if el.door_state == DOOR_OPEN else f"UNKNOWN_STATE({el.door_state})"
                error_msg = f"Elevator {eid} finished with doors not CLOSED (current state: {state_str})"
                final_check_errors.append(error_msg)
                elevators_ok = False

        if elevators_ok:
             print("Elevator Check: OK - All elevators empty and doors closed.")
        else:
             print("Elevator Check: FAILED")

        # Add final check errors to the main error list, prefixed
        self.errors.extend([f"Final State Error: {msg}" for msg in final_check_errors])

        # Return True only if NO errors were found throughout the entire process
        return not self.errors


    def calculate_performance(self, real_time):
        # ... (保持不变) ...
        t_run = max(real_time, self.total_runtime)
        total_weighted_time = 0
        total_weight = 0
        valid_passengers = 0
        if not self.passengers:
             wt = 0.0
        else:
            for p in self.passengers.values():
                if p.state == PASSENGER_ARRIVED and p.finish_time >= p.request_time:
                    completion_time = p.finish_time - p.request_time
                    total_weighted_time += completion_time * p.priority
                    total_weight += p.priority
                    valid_passengers += 1
                else:
                    if p.id in self.passengers and p.state != PASSENGER_ARRIVED:
                         print(f"Warning: Passenger {p.id} did not finish correctly for WT calculation (state={p.state}).")

            if total_weight > 0:
                wt = total_weighted_time / total_weight
            else:
                 if len(self.passengers) > 0 and valid_passengers == 0:
                     print("Warning: No passengers finished correctly, WT cannot be calculated accurately.")
                     wt = float('inf')
                 else:
                      wt = 0.0
        power_w = (self.power_arrive * 0.4 +
                   self.power_open * 0.1 +
                   self.power_close * 0.1)
        return {
            "T_run": t_run,
            "WT": wt,
            "W": power_w,
            "Arrives": self.power_arrive,
            "Opens": self.power_open,
            "Closes": self.power_close
        }