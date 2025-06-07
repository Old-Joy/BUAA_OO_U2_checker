# validator.py (HW7 适配 v1.5 - 强制重置乘客状态)
import re
import math
from collections import defaultdict, deque

MOVE_TIME_DEFAULT = 0.4
DOUBLE_CAR_SPEED = 0.2
DOOR_TIME = 0.4
EPSILON = 0.001
MAX_CAPACITY = 6
FLOOR_MIN = -4
FLOOR_MAX = 7
VALID_FLOORS_SET = set(range(FLOOR_MIN, 0)) | set(range(1, FLOOR_MAX + 1))
ELEVATOR_COUNT = 6
SCHE_HOLD_TIME = 1.0
SCHE_MAX_RESPONSE_TIME = 6.0
SCHE_TARGET_FLOORS_SET = {-2, -1, 1, 2, 3, 4, 5}
SCHE_VALID_SPEEDS = {0.2, 0.3, 0.4, 0.5}
UPDATE_HOLD_TIME = 1.0
UPDATE_MAX_RESPONSE_TIME = 6.0
UPDATE_TARGET_FLOORS_SET = {-2, -1, 1, 2, 3, 4, 5}

DOOR_CLOSED = 0; DOOR_OPEN = 1
PASSENGER_WAITING = 0; PASSENGER_INSIDE = 1; PASSENGER_ARRIVED = 2
ELEVATOR_IDLE = 0
ELEVATOR_SCHEDULING_PENDING = 1; ELEVATOR_SCHEDULING_ACTIVE = 2
ELEVATOR_UPDATING_PENDING = 3; ELEVATOR_UPDATING_ACTIVE = 4

def str_to_floor(floor_str):
    if not isinstance(floor_str, str) or not floor_str: return None
    prefix = floor_str[0]
    try: num = int(floor_str[1:])
    except (ValueError, IndexError): return None
    if prefix == 'B' and num > 0: floor_int = -num
    elif prefix == 'F' and num > 0: floor_int = num
    else: return None
    return floor_int if FLOOR_MIN <= floor_int <= FLOOR_MAX and floor_int != 0 else None

def floor_to_str(floor):
    if floor is None: return "InvalidFloor(None)"
    try: floor_int = int(floor)
    except (ValueError, TypeError): return f"InvalidFloor({floor})"
    if floor_int < 0 and floor_int >= FLOOR_MIN: return f"B{-floor_int}"
    if floor_int > 0 and floor_int <= FLOOR_MAX: return f"F{floor_int}"
    return f"InvalidFloor({floor_int})"

class TargetFloorState:
    def __init__(self, floor):
        self.transfer_floor = floor
        self.occupied_by = None
    def is_occupied(self):
        return self.occupied_by is not None
    def try_occupy(self, elevator_original_id):
        if self.occupied_by is None: self.occupied_by = elevator_original_id; return True
        elif self.occupied_by == elevator_original_id: return True
        else: return False
    def release(self, elevator_original_id):
        if self.occupied_by == elevator_original_id: self.occupied_by = None

class PassengerState:
    def __init__(self, id, priority, from_fl, to_fl, req_time):
        self.id=id; self.priority=priority; self.from_floor=from_fl; self.to_floor=to_fl;
        self.request_time=req_time; self.finish_time=-1.0; self.current_location=from_fl;
        self.state=PASSENGER_WAITING; self.current_elevator=-1; self.received_by_elevator=-1;
    def __repr__(self):
        loc=floor_to_str(self.current_location) if self.state!=PASSENGER_INSIDE else "In"
        st_map={0:"W", 1:"I", 2:"A"}; st=st_map.get(self.state, '?')
        el=f"E{self.current_elevator}" if self.state==PASSENGER_INSIDE else ""
        rcv=f"R{self.received_by_elevator}" if self.state==0 and self.received_by_elevator!=-1 else ""
        dest=floor_to_str(self.to_floor); return f"P{self.id}({loc}{el}{rcv}->{dest}@{st})"

class ElevatorState:
    def __init__(self, id):
        self.id = id; self.original_id = id; self.reset_state()
    def reset_state(self):
        self.current_floor = 1; self.door_state = DOOR_CLOSED; self.passengers = set()
        self.last_event_time = 0.0; self.last_action_finish_time = 0.0; self.received_passengers = set()
        self.current_speed = MOVE_TIME_DEFAULT; self.state = ELEVATOR_IDLE; self.schedule_info = {}
        self.update_info = {}; self.arrives_since_accept = 0; self.is_double_car = False
        self.partner_elevator_id = -1; self.shaft_id = self.original_id; self.min_floor = FLOOR_MIN
        self.max_floor = FLOOR_MAX
    @property
    def passenger_count(self): return len(self.passengers)
    def action_completed(self, finish_time): self.last_action_finish_time = finish_time
    def __repr__(self):
        ds= {0:"C", 1:"O"}.get(self.door_state, '?'); ss_map= {0:"IDLE", 1:"S_PEND", 2:"S_ACTV", 3:"U_PEND", 4:"U_ACTV"}
        ss= ss_map.get(self.state, '?'); fl= floor_to_str(self.current_floor); ps= sorted(list(self.passengers)); rps= sorted(list(self.received_passengers))
        spd = f"{self.current_speed:.1f}"; dbl = "DC" if self.is_double_car else ""; part = f"P{self.partner_elevator_id}" if self.is_double_car else ""
        shft_info = f"Sh{self.shaft_id}" if self.shaft_id != self.original_id or self.is_double_car else ""; range_s = f"[{floor_to_str(self.min_floor)}-{floor_to_str(self.max_floor)}]"
        return (f"E{self.original_id}(@{fl} D:{ds} S:{spd} R:{range_s} St:{ss} {dbl}{part}{shft_info} "
                f"In:{ps} Rcv:{rps} FinT:{self.last_action_finish_time:.2f})")

class OutputValidator:
    def __init__(self, stdin_file):
        self.errors = []; self.events = []; self.passengers = {}
        self.elevators = {i: ElevatorState(id=i) for i in range(1, ELEVATOR_COUNT + 1)}
        self.last_global_time = 0.0; self.power_arrive = 0; self.power_open = 0
        self.power_close = 0; self.total_runtime = 0.0; self.raw_requests = []
        self.active_shafts = set(range(1, ELEVATOR_COUNT + 1))
        self.target_floor_managers = {}
        self.parse_stdin(stdin_file)

    def add_error(self, message, timestamp=None):
        ts_str = f" (at time ~{timestamp:.4f})" if timestamp is not None else ""
        full_message = f"Validation Error: {message}{ts_str}"
        if not self.errors or self.errors[-1] != full_message: self.errors.append(full_message)

    def parse_stdin(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                 for line_num, line in enumerate(f, 1):
                    line = line.strip();
                    if not line: continue
                    ts_match=re.match(r"\[\s*(\d+\.\d+)\s*\]",line);
                    if not ts_match: self.add_error(f"Invalid timestamp stdin L{line_num}: '{line}'"); continue
                    ts=float(ts_match.group(1)); content=line[ts_match.end():].strip()
                    passenger_pattern = r"(\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)";
                    sche_pattern = r"SCHE-(\d+)-(\d+\.\d+)-([BF]\d+)"
                    update_pattern = r"UPDATE-(\d+)-(\d+)-([BF]\d+)"
                    passenger_match = re.fullmatch(passenger_pattern, content)
                    sche_match = re.fullmatch(sche_pattern, content)
                    update_match = re.fullmatch(update_pattern, content)
                    if passenger_match:
                         g = passenger_match.groups(); pid=int(g[0]); prio=int(g[1]); f_fl=str_to_floor(g[2]); t_fl=str_to_floor(g[3]); valid=True
                         if f_fl is None: self.add_error(f"Invalid FROM '{g[2]}' stdin L{line_num}"); valid=False
                         if t_fl is None: self.add_error(f"Invalid TO '{g[3]}' stdin L{line_num}"); valid=False
                         if f_fl is not None and t_fl is not None and f_fl==t_fl: self.add_error(f"Same FROM/TO '{g[2]}' stdin L{line_num}"); valid=False
                         if not(1<=prio<=100): self.add_error(f"Invalid PRI {prio} stdin L{line_num}"); valid=False
                         if pid<1: self.add_error(f"Invalid PID {pid} stdin L{line_num}"); valid=False
                         if pid in self.passengers: self.add_error(f"Duplicate PID {pid} stdin L{line_num}"); valid=False
                         if valid:
                            self.passengers[pid] = PassengerState(pid, prio, f_fl, t_fl, ts)
                            self.raw_requests.append({'type':'p','time':ts,'id':pid,'from':f_fl,'to':t_fl})
                    elif sche_match:
                         g = sche_match.groups(); eid=int(g[0]); spd_val=float(g[1]); t_fl=str_to_floor(g[2]); valid=True
                         if not(1<=eid<=ELEVATOR_COUNT): self.add_error(f"Invalid EID {eid} SCHE L{line_num}"); valid=False
                         if spd_val not in SCHE_VALID_SPEEDS: self.add_error(f"Invalid Speed {spd_val} SCHE L{line_num}"); valid=False
                         if t_fl is None or t_fl not in SCHE_TARGET_FLOORS_SET: self.add_error(f"Invalid Target '{g[2]}' SCHE L{line_num}"); valid=False
                         if valid: self.raw_requests.append({'type':'s','time':ts,'eid':eid,'spd':spd_val,'tfl':t_fl})
                    elif update_match:
                        g = update_match.groups()
                        try:
                            e_a_id = int(g[0]); e_b_id = int(g[1]); t_fl = str_to_floor(g[2]); valid = True
                            if not(1<=e_a_id<=ELEVATOR_COUNT) or not(1<=e_b_id<=ELEVATOR_COUNT): self.add_error(f"Invalid EID in UPDATE {g[0]}/{g[1]} L{line_num}"); valid=False
                            if e_a_id == e_b_id: self.add_error(f"Same EID in UPDATE {g[0]} L{line_num}"); valid=False
                            if t_fl is None or t_fl not in UPDATE_TARGET_FLOORS_SET: self.add_error(f"Invalid Target Floor '{g[2]}' UPDATE L{line_num}"); valid=False
                            if valid: self.raw_requests.append({'type':'u','time':ts,'e_a':e_a_id,'e_b':e_b_id,'tfl':t_fl})
                        except ValueError: self.add_error(f"Data type error UPDATE stdin L{line_num}")
                    else:
                         self.add_error(f"Unrecognized stdin content L{line_num}: '{content}'")
        except FileNotFoundError: self.add_error(f"Stdin file not found: {filename}")
        except Exception as e: self.add_error(f"Error reading stdin {filename}: {e}")
        self.raw_requests.sort(key=lambda x: x['time'])

    def parse_output_line(self, line):
        line = line.strip();
        if not line: return None
        ts_match = re.match(r"\[\s*(\d+\.\d+)\s*\]", line)
        if not ts_match: self.add_error(f"Output line missing/invalid timestamp: '{line}'"); return None
        ts_str = ts_match.group(1); content = line[ts_match.end():].strip()
        try: t = float(ts_str)
        except ValueError: self.add_error(f"Invalid timestamp value '{ts_str}': '{line}'"); return None
        if t < self.last_global_time - EPSILON: self.add_error(f"Timestamp non-decreasing: {t:.4f} < {self.last_global_time:.4f}", t)
        self.last_global_time = max(self.last_global_time, t); self.total_runtime = self.last_global_time

        parsed_event = None; event_type = None
        pid=None; eid=None; fl=None; flag=None; spd=None; tfl=None; e_a=None; e_b=None; m=None
        try:
            m_arrive = re.fullmatch(r"ARRIVE-([BF]\d+)-(\d+)", content)
            m_open = re.fullmatch(r"OPEN-([BF]\d+)-(\d+)", content)
            m_close = re.fullmatch(r"CLOSE-([BF]\d+)-(\d+)", content)
            m_receive = re.fullmatch(r"RECEIVE-(\d+)-(\d+)", content)
            m_in = re.fullmatch(r"IN-(\d+)-([BF]\d+)-(\d+)", content)
            m_out = re.fullmatch(r"OUT-([SF])-(\d+)-([BF]\d+)-(\d+)", content)
            m_sb = re.fullmatch(r"SCHE-BEGIN-(\d+)", content)
            m_se = re.fullmatch(r"SCHE-END-(\d+)", content)
            m_sa = re.fullmatch(r"SCHE-ACCEPT-(\d+)-(\d+\.\d+)-([BF]\d+)", content)
            m_ua = re.fullmatch(r"UPDATE-ACCEPT-(\d+)-(\d+)-([BF]\d+)", content)
            m_ub = re.fullmatch(r"UPDATE-BEGIN-(\d+)-(\d+)", content)
            m_ue = re.fullmatch(r"UPDATE-END-(\d+)-(\d+)", content)

            if m_arrive: m=m_arrive; event_type = "ARRIVE";
            elif m_open: m=m_open; event_type = "OPEN";
            elif m_close: m=m_close; event_type = "CLOSE";
            elif m_receive: m=m_receive; event_type = "RECEIVE";
            elif m_in: m=m_in; event_type = "IN";
            elif m_out: m=m_out; event_type = "OUT";
            elif m_sb: m=m_sb; event_type = "SCHE-BEGIN";
            elif m_se: m=m_se; event_type = "SCHE-END";
            elif m_sa: m=m_sa; event_type = "SCHE-ACCEPT";
            elif m_ua: m=m_ua; event_type = "UPDATE-ACCEPT";
            elif m_ub: m=m_ub; event_type = "UPDATE-BEGIN";
            elif m_ue: m=m_ue; event_type = "UPDATE-END";
            else: m = None

            if m:
                 g = m.groups()
                 if event_type in ["ARRIVE", "OPEN", "CLOSE"]:
                     fl = str_to_floor(g[0]); eid = int(g[1])
                     if fl is None or not(1 <= eid <= ELEVATOR_COUNT): raise ValueError(f"Invalid {event_type} args")
                     parsed_event = {"type": event_type, "time": t, "floor": fl, "elevator_id": eid}
                 elif event_type == "RECEIVE":
                     pid = int(g[0]); eid = int(g[1])
                     if pid not in self.passengers or not(1<=eid<=ELEVATOR_COUNT): raise ValueError("Invalid RECEIVE args")
                     parsed_event = {"type": event_type, "time": t, "person_id": pid, "elevator_id": eid}
                 elif event_type == "IN":
                     pid = int(g[0]); fl = str_to_floor(g[1]); eid = int(g[2])
                     if pid not in self.passengers or fl is None or not(1 <= eid <= ELEVATOR_COUNT): raise ValueError("Invalid IN args")
                     parsed_event = {"type": event_type, "time": t, "person_id": pid, "floor": fl, "elevator_id": eid}
                 elif event_type == "OUT":
                     flag = g[0]; pid = int(g[1]); fl = str_to_floor(g[2]); eid = int(g[3])
                     if flag not in ['S', 'F'] or pid not in self.passengers or fl is None or not(1 <= eid <= ELEVATOR_COUNT): raise ValueError("Invalid OUT args")
                     parsed_event = {"type": event_type, "time": t, "success": flag == 'S', "person_id": pid, "floor": fl, "elevator_id": eid}
                 elif event_type in ["SCHE-BEGIN", "SCHE-END"]:
                     eid = int(g[0])
                     if not(1 <= eid <= ELEVATOR_COUNT): raise ValueError(f"Invalid {event_type} args")
                     parsed_event = {"type": event_type, "time": t, "elevator_id": eid}
                 elif event_type == "SCHE-ACCEPT":
                     eid = int(g[0]); spd = float(g[1]); tfl = str_to_floor(g[2])
                     if not(1 <= eid <= ELEVATOR_COUNT) or spd not in SCHE_VALID_SPEEDS or tfl is None or tfl not in SCHE_TARGET_FLOORS_SET: raise ValueError("Invalid SCHE-ACCEPT args")
                     parsed_event = {"type": event_type, "time": t, "elevator_id": eid, "speed": spd, "target_floor": tfl}
                 elif event_type == "UPDATE-ACCEPT":
                     e_a = int(g[0]); e_b = int(g[1]); tfl = str_to_floor(g[2])
                     if not(1<=e_a<=ELEVATOR_COUNT) or not(1<=e_b<=ELEVATOR_COUNT) or e_a == e_b or tfl is None or tfl not in UPDATE_TARGET_FLOORS_SET: raise ValueError("Invalid UPDATE-ACCEPT args")
                     parsed_event = {"type": event_type, "time": t, "elevator_a_id": e_a, "elevator_b_id": e_b, "target_floor": tfl}
                 elif event_type == "UPDATE-BEGIN":
                     e_a = int(g[0]); e_b = int(g[1])
                     if not(1<=e_a<=ELEVATOR_COUNT) or not(1<=e_b<=ELEVATOR_COUNT) or e_a == e_b: raise ValueError("Invalid UPDATE-BEGIN args")
                     parsed_event = {"type": event_type, "time": t, "elevator_a_id": e_a, "elevator_b_id": e_b}
                 elif event_type == "UPDATE-END":
                     e_a = int(g[0]); e_b = int(g[1])
                     if not(1<=e_a<=ELEVATOR_COUNT) or not(1<=e_b<=ELEVATOR_COUNT) or e_a == e_b: raise ValueError("Invalid UPDATE-END args")
                     parsed_event = {"type": event_type, "time": t, "elevator_a_id": e_a, "elevator_b_id": e_b}

        except (ValueError, IndexError, AttributeError) as e:
             errmsg = f"Error processing args for {event_type or 'Unknown Type'}: {e} (line: '{line}')"
             if not self.errors or errmsg not in self.errors[-1]: self.add_error(errmsg, t)
             return None
        except re.error as e_re:
             self.add_error(f"Regex error during parsing: {e_re} (line: '{line}')", t); return None

        if m is None:
             err_msg_unrec = f"Unrecognized output event format: '{content}' (line: '{line}')"
             if not self.errors or err_msg_unrec not in self.errors[-1]: self.add_error(err_msg_unrec, t)
        elif parsed_event is None:
             self.add_error(f"Internal error: Matched '{event_type}' but failed to create parsed_event dict for line: '{line}'", t)

        return parsed_event

    def validate_event(self, event):
        """根据 HW7 规则验证单个事件并更新状态 (修复 IN 可达性, SCHE-BEGIN rp 错误)"""
        if event is None: return False
        etype=event["type"]; t=event["time"]

        eid = event.get("elevator_id")
        e_a_id = event.get("elevator_a_id")
        e_b_id = event.get("elevator_b_id")
        el_state_obj = self.elevators.get(eid) if eid else None # Get state obj by original id
        el_a = self.elevators.get(e_a_id) if e_a_id else None
        el_b = self.elevators.get(e_b_id) if e_b_id else None

        if etype.startswith("UPDATE"):
            if el_a is None or el_b is None: self.add_error(f"{etype} references invalid elevator {e_a_id}/{e_b_id}", t); return False
            if el_a.shaft_id not in self.active_shafts or el_b.shaft_id not in self.active_shafts: self.add_error(f"{etype} involves elevator in inactive shaft",t); return False
            if el_a.is_double_car or el_b.is_double_car: self.add_error(f"{etype} involves already double-car elevator",t); return False
        elif el_state_obj is None: self.add_error(f"Event missing/invalid EID {eid}: {event}", t); return False
        elif el_state_obj.shaft_id not in self.active_shafts: self.add_error(f"{etype} for E{el_state_obj.original_id} in inactive shaft {el_state_obj.shaft_id}",t); return False
        el = el_state_obj

        if el: el.last_event_time = t
        if el_a: el_a.last_event_time = t
        if el_b: el_b.last_event_time = t

        pid=event.get("person_id"); p=self.passengers.get(pid) if pid else None
        floor = event.get("floor")

        state = el.state if el else None
        state_a = el_a.state if el_a else None
        state_b = el_b.state if el_b else None
        is_sche_p = (state == ELEVATOR_SCHEDULING_PENDING)
        is_sche_a = (state == ELEVATOR_SCHEDULING_ACTIVE)
        is_upd_p = (state == ELEVATOR_UPDATING_PENDING)
        is_upd_a = (state == ELEVATOR_UPDATING_ACTIVE)
        is_updating = is_upd_p or is_upd_a
        is_scheduling = is_sche_p or is_sche_a

        try:
            if etype == "SCHE-ACCEPT":
                if el is None: return False
                spd = event["speed"]; tfl = event["target_floor"]
                if state not in [ELEVATOR_IDLE, None]: self.add_error(f"SCHE-ACCEPT E{el.original_id} 但非 IDLE (state={state})",t)
                if el.is_double_car: self.add_error(f"SCHE-ACCEPT E{el.original_id} 该电梯已是双轿厢",t)
                el.state = ELEVATOR_SCHEDULING_PENDING; el.schedule_info={'accept_time':t, 'speed':spd, 'target_floor':tfl}; el.arrives_since_accept=0;
                return True
            elif etype == "UPDATE-ACCEPT":
                tfl = event["target_floor"]
                if state_a != ELEVATOR_IDLE or state_b != ELEVATOR_IDLE: self.add_error(f"UPDATE-ACCEPT {e_a_id}-{e_b_id}: 电梯非 IDLE", t)
                el_a.state = ELEVATOR_UPDATING_PENDING; el_b.state = ELEVATOR_UPDATING_PENDING
                el_a.update_info = {'accept_time': t, 'target_floor': tfl, 'partner_id': e_b_id, 'is_a': True}
                el_b.update_info = {'accept_time': t, 'target_floor': tfl, 'partner_id': e_a_id, 'is_a': False}
                el_a.arrives_since_accept = 0; el_b.arrives_since_accept = 0
                return True
            elif etype == "UPDATE-BEGIN":
                if state_a != ELEVATOR_UPDATING_PENDING or state_b != ELEVATOR_UPDATING_PENDING: self.add_error(f"UPDATE-BEGIN {e_a_id}-{e_b_id}: 电梯非 U_PEND", t); return False
                if el_a.arrives_since_accept > 2: self.add_error(f"UPDATE-BEGIN {e_a_id}-{e_b_id}: E{e_a_id} ARRIVE 次数 > 2", t)
                if el_b.arrives_since_accept > 2: self.add_error(f"UPDATE-BEGIN {e_a_id}-{e_b_id}: E{e_b_id} ARRIVE 次数 > 2", t)
                if el_a.door_state != DOOR_CLOSED: self.add_error(f"UPDATE-BEGIN {e_a_id}-{e_b_id}: E{e_a_id} 门未关", t)
                if el_b.door_state != DOOR_CLOSED: self.add_error(f"UPDATE-BEGIN {e_a_id}-{e_b_id}: E{e_b_id} 门未关", t)
                if el_a.passenger_count > 0: self.add_error(f"UPDATE-BEGIN {e_a_id}-{e_b_id}: E{e_a_id} 内有人", t)
                if el_b.passenger_count > 0: self.add_error(f"UPDATE-BEGIN {e_a_id}-{e_b_id}: E{e_b_id} 内有人", t)
                if t < el_a.last_action_finish_time - EPSILON: self.add_error(f"UPDATE-BEGIN E{e_a_id} 时未停止",t)
                if t < el_b.last_action_finish_time - EPSILON: self.add_error(f"UPDATE-BEGIN E{e_b_id} 时未停止",t)
                el_a.state = ELEVATOR_UPDATING_ACTIVE; el_b.state = ELEVATOR_UPDATING_ACTIVE
                el_a.update_info['begin_time'] = t; el_b.update_info['begin_time'] = t
                passengers_to_check = list(self.passengers.values())
                for rp in passengers_to_check:
                    if rp.received_by_elevator == e_a_id or rp.received_by_elevator == e_b_id: rp.received_by_elevator = -1
                el_a.received_passengers.clear(); el_b.received_passengers.clear()
                return True
            elif etype == "UPDATE-END":
                if state_a != ELEVATOR_UPDATING_ACTIVE or state_b != ELEVATOR_UPDATING_ACTIVE: self.add_error(f"UPDATE-END {e_a_id}-{e_b_id}: 电梯非 U_ACTV", t); return False
                begin_t_a = el_a.update_info.get('begin_time', -1.0); accept_t_a = el_a.update_info.get('accept_time', -1.0)
                if begin_t_a < 0 or accept_t_a < 0: self.add_error(f"UPDATE-END {e_a_id}-{e_b_id}: 内部错误 - 缺少时间信息", t)
                else:
                     hold_time = t - begin_t_a
                     if hold_time < UPDATE_HOLD_TIME - EPSILON*10: self.add_error(f"UPDATE 保持时间 {e_a_id}-{e_b_id} 过短: {hold_time:.4f}s < {UPDATE_HOLD_TIME}s", t)
                     response_time = t - accept_t_a
                     if response_time > UPDATE_MAX_RESPONSE_TIME + EPSILON*10: self.add_error(f"UPDATE 响应时间 {e_a_id}-{e_b_id} 过长: {response_time:.4f}s > {UPDATE_MAX_RESPONSE_TIME}s", t)
                target_floor = el_a.update_info.get('target_floor');
                if target_floor is None: self.add_error(f"UPDATE-END {e_a_id}-{e_b_id}: 内部错误 - 缺少换乘楼层",t); return False
                initial_a_floor = target_floor + 1; initial_b_floor = target_floor - 1
                if initial_a_floor == 0: initial_a_floor = 1
                if initial_b_floor == 0: initial_b_floor = -1
                if initial_a_floor > FLOOR_MAX : initial_a_floor = FLOOR_MAX
                if initial_b_floor < FLOOR_MIN: initial_b_floor = FLOOR_MIN
                el_a.is_double_car = True; el_a.partner_elevator_id = e_b_id; el_a.shaft_id = e_b_id
                el_a.min_floor = target_floor; el_a.max_floor = FLOOR_MAX; el_a.current_floor = initial_a_floor
                el_a.current_speed = DOUBLE_CAR_SPEED; el_a.state = ELEVATOR_IDLE; el_a.update_info = {}; el_a.action_completed(t)
                el_b.is_double_car = True; el_b.partner_elevator_id = e_a_id; el_b.shaft_id = e_b_id
                el_b.min_floor = FLOOR_MIN; el_b.max_floor = target_floor; el_b.current_floor = initial_b_floor
                el_b.current_speed = DOUBLE_CAR_SPEED; el_b.state = ELEVATOR_IDLE; el_b.update_info = {}; el_b.action_completed(t)
                self.active_shafts.discard(e_a_id); self.target_floor_managers[e_b_id] = TargetFloorState(target_floor)
                return True

            if el is None: return False

            if is_updating or is_scheduling:
                if etype in ["RECEIVE", "IN"] and state == ELEVATOR_UPDATING_ACTIVE: self.add_error(f"{etype} E{el.original_id} 在 UPDATE ACTIVE 状态",t)
                if etype in ["OPEN", "CLOSE"] and state == ELEVATOR_UPDATING_ACTIVE : self.add_error(f"{etype} E{el.original_id} 在 UPDATE ACTIVE 状态",t)
                if etype == "ARRIVE" and state == ELEVATOR_UPDATING_ACTIVE: self.add_error(f"ARRIVE E{el.original_id} 在 UPDATE ACTIVE 状态", t)

            if etype == "ARRIVE":
                self.power_arrive += 1; floor = event["floor"]
                if floor is None: return False
                if is_upd_p or is_sche_p: el.arrives_since_accept += 1
                if el.door_state == DOOR_OPEN: self.add_error(f"E{el.original_id} ARRIVE @{floor_to_str(floor)} 时门开",t)
                if floor not in VALID_FLOORS_SET: self.add_error(f"E{el.original_id} ARRIVE 无效楼层 {floor_to_str(floor)}",t)
                f_diff=abs(floor - el.current_floor); cross0=(el.current_floor * floor == -1 and abs(el.current_floor) == 1)
                if not(f_diff == 1 or cross0) and floor != el.current_floor: self.add_error(f"E{el.original_id} 无效移动 {floor_to_str(el.current_floor)}->{floor_to_str(floor)}",t)
                if not (el.min_floor <= floor <= el.max_floor): self.add_error(f"E{el.original_id} ARRIVE @{floor_to_str(floor)} 超出范围 [{floor_to_str(el.min_floor)}-{floor_to_str(el.max_floor)}]",t)
                exp_move_t = el.current_speed; exp_arr_t = el.last_action_finish_time + exp_move_t
                if t < exp_arr_t - EPSILON*20: self.add_error(f"E{el.original_id} ARRIVE @{floor_to_str(floor)} 过早. T:{t:.4f}<Exp:{exp_arr_t:.4f}(Last:{el.last_action_finish_time:.4f},Spd:{el.current_speed:.1f})",t)
                is_leaving_transfer = False; tf_manager = self.target_floor_managers.get(el.shaft_id) if el.is_double_car else None
                if el.is_double_car and tf_manager and el.current_floor == tf_manager.transfer_floor and floor != tf_manager.transfer_floor: is_leaving_transfer = True
                if el.passenger_count == 0 and not is_sche_a and not is_upd_a and not el.received_passengers and not is_leaving_transfer: self.add_error(f"E{el.original_id} 空载移动 (ARRIVE {floor_to_str(floor)})",t)
                if el.is_double_car:
                    partner = self.elevators.get(el.partner_elevator_id)
                    if partner is None or partner.shaft_id != el.shaft_id or not partner.is_double_car: self.add_error(f"内部错误: E{el.original_id} 伙伴 E{el.partner_elevator_id} 状态异常", t)
                    elif tf_manager:
                        if floor == tf_manager.transfer_floor:
                            if not tf_manager.try_occupy(el.original_id): self.add_error(f"碰撞: E{el.original_id} 到达换乘层 {floor_to_str(floor)} 时已被 E{tf_manager.occupied_by} 占用",t)
                        if el.current_floor == tf_manager.transfer_floor and floor != tf_manager.transfer_floor : tf_manager.release(el.original_id)
                        partner_current_floor = partner.current_floor
                        if floor != tf_manager.transfer_floor and partner_current_floor != tf_manager.transfer_floor:
                            is_a = (el.min_floor >= partner.min_floor)
                            if is_a and floor <= partner_current_floor: self.add_error(f"位置碰撞: E{el.original_id}(A) @{floor_to_str(floor)} <= E{partner.original_id}(B) @{floor_to_str(partner_current_floor)}",t)
                            elif not is_a and floor >= partner_current_floor: self.add_error(f"位置碰撞: E{el.original_id}(B) @{floor_to_str(floor)} >= E{partner.original_id}(A) @{floor_to_str(partner_current_floor)}",t)
                    else: self.add_error(f"内部错误: E{el.original_id} 双轿厢但无井道 {el.shaft_id} 换乘管理器",t)
                el.current_floor = floor; el.action_completed(t); return True

            elif etype == "OPEN":
                self.power_open += 1; floor = event["floor"]
                if is_upd_a: self.add_error(f"E{el.original_id} OPEN @{floor_to_str(floor)} 在 UPDATE ACTIVE 状态",t)
                is_at_sche_target = is_sche_a and floor == el.schedule_info.get('target_floor')
                if is_sche_a and not is_at_sche_target: self.add_error(f"E{el.original_id} OPEN @{floor_to_str(floor)} 在 SCHE ACTIVE 状态 (非目标)",t)
                if el.door_state != DOOR_CLOSED: self.add_error(f"E{el.original_id} OPEN @{floor_to_str(floor)} 但门未关",t)
                if floor != el.current_floor: self.add_error(f"E{el.original_id} OPEN @ 错误楼层 {floor_to_str(floor)} (当前:{floor_to_str(el.current_floor)})",t)
                if t < el.last_action_finish_time - EPSILON*10: self.add_error(f"E{el.original_id} OPEN @{floor_to_str(floor)} 过早 T:{t:.4f}<PrevFin:{el.last_action_finish_time:.4f}",t)
                el.door_state = DOOR_OPEN; el.action_completed(t); return True

            elif etype == "CLOSE":
                self.power_close += 1; floor = event["floor"]
                is_at_sche_target = is_sche_a and floor == el.schedule_info.get('target_floor')
                if is_upd_a: self.add_error(f"E{el.original_id} CLOSE @{floor_to_str(floor)} 在 UPDATE ACTIVE 状态",t)
                if is_sche_a and not is_at_sche_target: self.add_error(f"E{el.original_id} CLOSE @{floor_to_str(floor)} 在 SCHE ACTIVE 状态 (非目标)",t)
                if el.door_state != DOOR_OPEN: self.add_error(f"E{el.original_id} CLOSE @{floor_to_str(floor)} 但门未开",t)
                if floor != el.current_floor: self.add_error(f"E{el.original_id} CLOSE @ 错误楼层 {floor_to_str(floor)} (当前:{floor_to_str(el.current_floor)})",t)
                min_dur = SCHE_HOLD_TIME if is_at_sche_target else DOOR_TIME
                open_t = -1.0;
                for i in range(len(self.events) - 1, -1, -1):
                    prev = self.events[i];
                    if prev.get('elevator_id') == el.original_id and prev.get('floor') == floor:
                        if prev['type'] == 'OPEN': open_t = prev['time']; break
                        if prev['type'] == 'CLOSE': open_t = -2.0; break
                if open_t == -1.0: self.add_error(f"E{el.original_id} CLOSE @{floor_to_str(floor)}: 未找到对应 OPEN",t)
                elif open_t >= 0:
                    dur = t - open_t
                    if dur < min_dur - EPSILON*10: mode = "SCHE" if is_at_sche_target else "norm"; self.add_error(f"E{el.original_id} 门 @{floor_to_str(floor)} 开启过短 ({mode}):{dur:.4f}s<{min_dur:.1f}s",t)
                el.door_state = DOOR_CLOSED; el.action_completed(t); return True

            elif etype == "RECEIVE":
                 if is_upd_a: self.add_error(f"RECEIVE-{pid}-{el.original_id} 在 UPDATE ACTIVE 状态",t)
                 if is_sche_a: self.add_error(f"RECEIVE-{pid}-{el.original_id} 在 SCHE ACTIVE 状态",t)
                 if p is None: return False
                 if p.state != PASSENGER_WAITING: self.add_error(f"RECEIVE-{pid}-{el.original_id} 乘客非 WAITING ({p.state})",t)
                 if p.received_by_elevator != -1:
                      if p.received_by_elevator != el.original_id: self.add_error(f"RECEIVE-{pid}-{el.original_id} 乘客已被 E{p.received_by_elevator} 接收",t)
                      else: self.add_error(f"重复 RECEIVE-{pid}-{el.original_id}", t)
                 p.received_by_elevator = el.original_id; el.received_passengers.add(pid); return True

            elif etype == "IN":
                floor = event["floor"]; pid = event["person_id"]; p = self.passengers.get(pid)
                if floor is None or p is None or el is None: return False
                if is_upd_a: self.add_error(f"P{pid} IN E{el.original_id} @{floor_to_str(floor)} 在 UPDATE ACTIVE 状态",t); return False
                if is_sche_a: self.add_error(f"P{pid} IN E{el.original_id} @{floor_to_str(floor)} 在 SCHE ACTIVE 状态",t); return False
                if el.door_state != DOOR_OPEN: self.add_error(f"P{pid} IN E{el.original_id} @{floor_to_str(floor)} 门未开",t)
                if el.passenger_count >= MAX_CAPACITY: self.add_error(f"E{el.original_id} 超载 ({MAX_CAPACITY}) IN P{pid} @{floor_to_str(floor)}",t)
                if floor != el.current_floor: self.add_error(f"P{pid} IN E{el.original_id} @ 错误楼层 {floor_to_str(floor)} (E@ {floor_to_str(el.current_floor)})",t)
                if p.state != PASSENGER_WAITING: self.add_error(f"P{pid} IN E{el.original_id} @{floor_to_str(floor)} 但非 WAITING (state={p.state})",t)
                elif floor != p.current_location: self.add_error(f"P{pid} IN E{el.original_id} @{floor_to_str(floor)}, 但 P 等待在 {floor_to_str(p.current_location)}",t)
                if p.received_by_elevator != el.original_id: self.add_error(f"P{pid} IN E{el.original_id} @{floor_to_str(floor)}, 但未被其接收 (RcvBy={p.received_by_elevator})",t)

                can_reach_destination_or_transfer = False
                if el.is_double_car:
                    tf_manager = self.target_floor_managers.get(el.shaft_id)
                    if tf_manager:
                        transfer_floor = tf_manager.transfer_floor
                        if el.min_floor <= p.to_floor <= el.max_floor:
                            can_reach_destination_or_transfer = True
                        elif el.min_floor <= transfer_floor <= el.max_floor:
                            can_reach_destination_or_transfer = True
                    else: self.add_error(f"内部错误: E{el.original_id} 双轿厢但无井道 {el.shaft_id} 换乘管理器",t)
                else:
                    if el.min_floor <= p.to_floor <= el.max_floor:
                        can_reach_destination_or_transfer = True

                if not can_reach_destination_or_transfer:
                    self.add_error(f"P{pid} IN E{el.original_id} @{floor_to_str(floor)} 但电梯无法将其送达目的地 {floor_to_str(p.to_floor)} 或换乘层 (范围 [{floor_to_str(el.min_floor)}-{floor_to_str(el.max_floor)}])",t)

                p.state = PASSENGER_INSIDE; p.current_elevator = el.original_id; p.current_location = -999; p.received_by_elevator = -1
                if pid in el.received_passengers: el.received_passengers.remove(pid)
                if pid not in el.passengers: el.passengers.add(pid)
                else: self.add_error(f"P{pid} IN E{el.original_id} 但已在内部", t)
                return True

            elif etype == "OUT":
                succ = event["success"]; floor = event["floor"]; pid = event["person_id"]; p = self.passengers.get(pid)
                if floor is None or p is None or el is None: return False
                if el.door_state != DOOR_OPEN: self.add_error(f"P{pid} OUT E{el.original_id} @{floor_to_str(floor)} 门未开",t)
                if floor != el.current_floor: self.add_error(f"P{pid} OUT E{el.original_id} @ 错误楼层 {floor_to_str(floor)} (E@ {floor_to_str(el.current_floor)})",t)
                if p.state != PASSENGER_INSIDE or p.current_elevator != el.original_id: self.add_error(f"P{pid} OUT E{el.original_id} @{floor_to_str(floor)} 但未在此电梯内 (st={p.state}, curE={p.current_elevator})",t)
                is_dest = (floor == p.to_floor)
                if succ and not is_dest: self.add_error(f"OUT-S P{pid} E{el.original_id} @{floor_to_str(floor)} 但非目的地 ({floor_to_str(p.to_floor)})",t)
                if not succ and is_dest: self.add_error(f"OUT-F P{pid} E{el.original_id} @ 目的地 {floor_to_str(floor)}. 应为 OUT-S",t)
                p.current_elevator = -1; p.current_location = floor
                if pid in el.passengers: el.passengers.remove(pid)
                if succ: p.state = PASSENGER_ARRIVED; p.finish_time = t
                else: p.state = PASSENGER_WAITING
                p.received_by_elevator = -1
                if pid in el.received_passengers: el.received_passengers.remove(pid)
                return True

            elif etype == "SCHE-BEGIN":
                if is_updating: self.add_error(f"SCHE-BEGIN E{el.original_id} 在 UPDATING 状态 (state={state})",t); return False
                if el.is_double_car: self.add_error(f"SCHE-BEGIN E{el.original_id} 该电梯已是双轿厢",t)
                if not is_sche_p: self.add_error(f"SCHE-BEGIN E{el.original_id} 但非 S_PEND (state={state})",t); return False
                s_info = el.schedule_info
                if el.arrives_since_accept > 2: self.add_error(f"SCHE-BEGIN E{el.original_id} 在 {el.arrives_since_accept}>2 次 ARRIVE 后",t)
                if el.door_state != DOOR_CLOSED: self.add_error(f"SCHE-BEGIN E{el.original_id} 门未关",t)
                if t < el.last_action_finish_time - EPSILON: self.add_error(f"SCHE-BEGIN E{el.original_id} 时未停止",t)
                el.state = ELEVATOR_SCHEDULING_ACTIVE; el.current_speed = s_info.get('speed', MOVE_TIME_DEFAULT); el.schedule_info['begin_time'] = t
                cancelled_passenger_ids = list(el.received_passengers)
                el.received_passengers.clear()
                for rpid in cancelled_passenger_ids:
                    rp = self.passengers.get(rpid)
                    if rp and rp.received_by_elevator == el.original_id:
                        rp.received_by_elevator = -1
                return True

            elif etype == "SCHE-END":
                if is_updating: self.add_error(f"SCHE-END E{el.original_id} 在 UPDATING 状态 (state={state})",t); return False
                if not is_sche_a: self.add_error(f"SCHE-END E{el.original_id} 但非 S_ACTV (state={state})",t); return False
                s_info = el.schedule_info; t_fl = s_info.get('target_floor')
                if t_fl is None: self.add_error(f"SCHE-END E{el.original_id}: 内部错误 - 无目标楼层",t)
                elif el.current_floor != t_fl: self.add_error(f"SCHE-END E{el.original_id} @ 错误楼层 {floor_to_str(el.current_floor)} (目标:{floor_to_str(t_fl)})",t)
                if el.passenger_count > 0: self.add_error(f"SCHE-END E{el.original_id} 内有 {el.passenger_count} P",t)
                if el.door_state != DOOR_CLOSED: self.add_error(f"SCHE-END E{el.original_id} 门未关",t)
                acc_t = s_info.get('accept_time', -1.0); comp_t = t - acc_t;
                if acc_t<0: self.add_error(f"SCHE-END E{el.original_id}: 未找到 Accept 时间",t)
                elif comp_t > SCHE_MAX_RESPONSE_TIME + EPSILON*10: self.add_error(f"SCHE E{el.original_id} 超时: {comp_t:.4f}s>{SCHE_MAX_RESPONSE_TIME}s",t)
                fnd_c=False; fnd_o=False; c_t=-1.0; o_t=-1.0; s_idx=len(self.events)-1
                while s_idx >= 0:
                    prev=self.events[s_idx];
                    if prev.get('elevator_id')!=el.original_id or prev.get('floor')!=t_fl: s_idx-=1; continue
                    if not fnd_c and prev['type']=='CLOSE': fnd_c=True; c_t=prev['time'];
                    elif fnd_c and not fnd_o and prev['type']=='OPEN':
                        fnd_o=True; o_t=prev['time']; hold=c_t-o_t;
                        if hold<SCHE_HOLD_TIME-EPSILON*10: self.add_error(f"SCHE 保持时间 E{el.original_id}@{floor_to_str(t_fl)} 过短:{hold:.4f}s<{SCHE_HOLD_TIME}s",t)
                        break
                    elif fnd_c and prev['type'] not in ['OUT','OPEN']: break
                    s_idx -= 1
                if not fnd_c or not fnd_o: self.add_error(f"SCHE-END E{el.original_id}: 未找到有效 OPEN/CLOSE({SCHE_HOLD_TIME}s+) 序列 @ Tgt {floor_to_str(t_fl)}",t)
                el.state = ELEVATOR_IDLE; el.current_speed = MOVE_TIME_DEFAULT; el.schedule_info = {};
                el.action_completed(t); return True

        except Exception as e:
             self.add_error(f"验证事件 {event} 时发生内部错误: {e}",t)
             import traceback; self.add_error(f"Traceback: {traceback.format_exc()}",t); return False

        self.add_error(f"未知的事件类型 '{etype}' 无法验证",t); return False


    def validate_output(self, output_lines):
        """HW7 输出验证主函数 """
        self.errors = []
        self.events = []
        self.last_global_time = 0.0
        self.power_arrive = 0
        self.power_open = 0
        self.power_close = 0
        self.total_runtime = 0.0
        self.active_shafts = set(range(1, ELEVATOR_COUNT + 1))
        self.target_floor_managers = {}

        for el in self.elevators.values():
            el.reset_state()

        for p in self.passengers.values():
            try:
                p.state = PASSENGER_WAITING
                p.current_location = p.from_floor
                p.current_elevator = -1
                p.received_by_elevator = -1
                p.finish_time = -1.0
            except Exception as e_reset_p:
                self.add_error(f"内部错误: 重置乘客 {p.id} 状态失败: {e_reset_p}")
                return False

        if not self.passengers and self.errors: return False
        elif not self.passengers and not output_lines: return True
        elif not self.passengers and output_lines: self.add_error("无请求但有输出"); return False

        parsed_events_raw = []
        for line in output_lines:
            event = self.parse_output_line(line)
            if event: parsed_events_raw.append(event)

        self.events = []
        for event in parsed_events_raw:
            if self.validate_event(event):
                self.events.append(event)

        print(f"\n--- 最终状态检查 (HW7 v{self.get_version()}) ---") #<--- 使用版本号
        final_errors = []
        all_p_ok = True
        if self.passengers:
            for pid, p_state in self.passengers.items():
                if p_state.state != PASSENGER_ARRIVED:
                    final_errors.append(f"P{pid} 未到达 (状态={p_state.state}, 位置={floor_to_str(p_state.current_location)}, 电梯={p_state.current_elevator})"); all_p_ok=False
            print(f"乘客检查: {'OK' if all_p_ok else 'FAILED'}")
        else: print("乘客检查: 跳过 (无请求)")

        all_e_ok = True
        for eid, el in self.elevators.items():
            if el.shaft_id in self.active_shafts or el.is_double_car:
                 if el.passenger_count > 0: final_errors.append(f"E{el.original_id} 结束时有乘客: {sorted(list(el.passengers))}"); all_e_ok=False
                 if el.door_state != DOOR_CLOSED: final_errors.append(f"E{el.original_id} 结束时门未关 (状态={el.door_state})"); all_e_ok=False
                 if el.state != ELEVATOR_IDLE: final_errors.append(f"E{el.original_id} 结束时状态非 IDLE (状态={el.state})"); all_e_ok=False
                 if el.received_passengers: final_errors.append(f"E{el.original_id} 结束时仍有接收乘客: {sorted(list(el.received_passengers))}"); all_e_ok=False
                 expected_speed = DOUBLE_CAR_SPEED if el.is_double_car else MOVE_TIME_DEFAULT
                 if abs(el.current_speed - expected_speed) > EPSILON: final_errors.append(f"E{el.original_id} 结束时速度错误 ({el.current_speed:.1f} 应为 {expected_speed:.1f})"); all_e_ok=False
                 tf_manager = self.target_floor_managers.get(el.shaft_id)
                 if el.is_double_car and tf_manager and tf_manager.occupied_by == el.original_id:
                     final_errors.append(f"E{el.original_id} 结束时仍占用换乘楼层 {floor_to_str(tf_manager.transfer_floor)}"); all_e_ok=False

        print(f"电梯检查: {'OK' if all_e_ok else 'FAILED'}")
        for msg in final_errors: self.add_error(f"最终状态错误: {msg}")
        return not self.errors


    def calculate_performance(self, real_time):
        """计算 HW7 性能"""
        t_run = max(real_time, self.total_runtime); wt = 0.0
        tot_wt_t = 0.0; tot_w = 0; finishers = 0
        if self.passengers:
            for p in self.passengers.values():
                if p.state == PASSENGER_ARRIVED and p.finish_time >= 0:
                    completion_time = p.finish_time - p.request_time
                    if completion_time >= 0:
                        tot_wt_t += completion_time * p.priority; tot_w += p.priority; finishers += 1
            if tot_w > 0: wt = tot_wt_t / tot_w
            elif len(self.passengers) > 0 and finishers == 0: wt = float('inf'); print("性能错误: 没有乘客正确完成, WT=inf")
        power_w = (self.power_arrive * 0.4 + self.power_open * 0.1 + self.power_close * 0.1)
        return { "T_run": t_run, "WT": wt, "W": power_w,
                 "Arrives": self.power_arrive, "Opens": self.power_open, "Closes": self.power_close }

    def get_version(self):
        return "v1.5"