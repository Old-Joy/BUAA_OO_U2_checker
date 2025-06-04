# validator.py (Corrected Indentation & Logic v13 - FINALLY Fixed SyntaxError in str_to_floor)
import re
import math
from collections import defaultdict, deque

# --- HW6 Constants ---
MOVE_TIME_DEFAULT = 0.4
DOOR_TIME = 0.4 # Min time door must stay open (normal)
EPSILON = 0.001 # Tolerance for float comparisons
MAX_CAPACITY = 6
FLOOR_MIN = -4
FLOOR_MAX = 7
VALID_FLOORS_SET = set(range(FLOOR_MIN, 0)) | set(range(1, FLOOR_MAX + 1))
ELEVATOR_COUNT = 6
SCHE_HOLD_TIME = 1.0 # SCHE 到达后开门保持时间
SCHE_MAX_RESPONSE_TIME = 6.0 # SCHE-ACCEPT 到 SCHE-END 最大允许时间
SCHE_TARGET_FLOORS_SET = {-2, -1, 1, 2, 3, 4, 5} # SCHE 允许的目标楼层
SCHE_VALID_SPEEDS = {0.2, 0.3, 0.4, 0.5} # 指导书指定的速度

# --- State Enums/Constants ---
DOOR_CLOSED = 0; DOOR_OPEN = 1
PASSENGER_WAITING = 0; PASSENGER_INSIDE = 1; PASSENGER_ARRIVED = 2
ELEVATOR_IDLE = 0; ELEVATOR_SCHEDULING_PENDING = 1; ELEVATOR_SCHEDULING_ACTIVE = 2

# --- Helper Functions ---
def str_to_floor(floor_str):
    if not isinstance(floor_str, str) or not floor_str: return None
    prefix = floor_str[0]
    # --- CORRECTED SYNTAX (v13 - Really fixed this time!) ---
    try:
        num = int(floor_str[1:])
    # --- END CORRECTION ---
    except (ValueError, IndexError):
        return None

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

# --- State Classes (HW6) ---
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
        self.id = id; self.current_floor = 1; self.door_state = DOOR_CLOSED;
        self.passengers = set(); self.last_event_time = 0.0; self.last_action_finish_time = 0.0;
        self.received_passengers = set(); self.scheduling_state = ELEVATOR_IDLE;
        self.current_speed = MOVE_TIME_DEFAULT; self.schedule_info = {};
        self.arrives_since_sche_accept = 0;
    @property
    def passenger_count(self): return len(self.passengers)
    def action_completed(self, finish_time): self.last_action_finish_time = finish_time
    def __repr__(self):
        ds= {0:"C", 1:"O"}.get(self.door_state, '?')
        ss= {0:"IDLE", 1:"PEND", 2:"ACTV"}.get(self.scheduling_state, '?')
        fl= floor_to_str(self.current_floor); ps= sorted(list(self.passengers)); rps= sorted(list(self.received_passengers))
        spd = f"{self.current_speed:.1f}";
        return (f"E{self.id}(@{fl} D:{ds} S:{spd} St:{ss} "
                f"In:{ps} Rcv:{rps} FinT:{self.last_action_finish_time:.2f})")

# --- Validator Class (HW6 Corrected v13) ---
class OutputValidator:
    def __init__(self, stdin_file):
        self.errors = []; self.events = []; self.passengers = {}
        self.elevators = {i: ElevatorState(id=i) for i in range(1, ELEVATOR_COUNT + 1)}
        self.last_global_time = 0.0; self.power_arrive = 0; self.power_open = 0
        self.power_close = 0; self.total_runtime = 0.0; self.raw_requests = []
        self.parse_stdin(stdin_file)

    def add_error(self, message, timestamp=None):
        ts_str = f" (at time ~{timestamp:.4f})" if timestamp is not None else ""
        full_message = f"Validation Error: {message}{ts_str}"
        if not self.errors or self.errors[-1] != full_message: self.errors.append(full_message)

    def parse_stdin(self, filename):
        # (No changes needed here)
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip();
                    if not line: continue
                    ts_match=re.match(r"\[\s*(\d+\.\d+)\s*\]",line);
                    if not ts_match: self.add_error(f"Invalid timestamp stdin L{line_num}: '{line}'"); continue
                    ts=float(ts_match.group(1)); content=line[ts_match.end():].strip()
                    passenger_pattern = r"(\d+)-PRI-(\d+)-FROM-([BF]\d+)-TO-([BF]\d+)"; sche_pattern = r"SCHE-(\d+)-(\d+\.\d+)-([BF]\d+)"
                    passenger_match = re.fullmatch(passenger_pattern, content)
                    if passenger_match:
                        p_id, pri, from_s, to_s = passenger_match.groups()
                        try:
                            pid=int(p_id); prio=int(pri); f_fl=str_to_floor(from_s); t_fl=str_to_floor(to_s); valid=True
                            if f_fl is None: self.add_error(f"Invalid FROM '{from_s}' stdin L{line_num}"); valid=False
                            if t_fl is None: self.add_error(f"Invalid TO '{to_s}' stdin L{line_num}"); valid=False
                            if f_fl is not None and t_fl is not None and f_fl==t_fl: self.add_error(f"Same FROM/TO '{from_s}' stdin L{line_num}"); valid=False
                            if not(1<=prio<=100): self.add_error(f"Invalid PRI {prio} stdin L{line_num}"); valid=False
                            if pid<1: self.add_error(f"Invalid PID {pid} stdin L{line_num}"); valid=False
                            if pid in self.passengers: self.add_error(f"Duplicate PID {pid} stdin L{line_num}"); valid=False
                            if valid:
                                self.passengers[pid] = PassengerState(pid, prio, f_fl, t_fl, ts)
                                self.raw_requests.append({'type':'p','time':ts,'id':pid,'from':f_fl,'to':t_fl})
                        except ValueError: self.add_error(f"Data type error passenger stdin L{line_num}")
                        continue
                    sche_match = re.fullmatch(sche_pattern, content)
                    if sche_match:
                        el_id, spd_s, fl_s = sche_match.groups()
                        try:
                            eid=int(el_id); spd_val=float(spd_s); t_fl=str_to_floor(fl_s); valid=True
                            if not(1<=eid<=ELEVATOR_COUNT): self.add_error(f"Invalid EID {eid} SCHE L{line_num}"); valid=False
                            if spd_val not in SCHE_VALID_SPEEDS: self.add_error(f"Invalid Speed {spd_val} SCHE L{line_num}"); valid=False
                            if t_fl is None or t_fl not in SCHE_TARGET_FLOORS_SET: self.add_error(f"Invalid Target '{fl_s}' SCHE L{line_num}"); valid=False
                            if valid: self.raw_requests.append({'type':'s','time':ts,'eid':eid,'spd':spd_val,'tfl':t_fl})
                        except ValueError: self.add_error(f"Data type error SCHE stdin L{line_num}")
                        continue
                    if not passenger_match and not sche_match: self.add_error(f"Unrecognized stdin content L{line_num}: '{content}' (full line: '{line}')")
        except FileNotFoundError: self.add_error(f"Stdin file not found: {filename}")
        except Exception as e: self.add_error(f"Error reading stdin {filename}: {e}")
        self.raw_requests.sort(key=lambda x: x['time'])


    def parse_output_line(self, line):
        """Parses a single line of HW6 output (Corrected timestamp/content extraction v7)."""
        # (No changes from v11)
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
        try:
            m = re.fullmatch(r"ARRIVE-([BF]\d+)-(\d+)", content)
            if m: event_type = "ARRIVE"; g = m.groups(); fl = str_to_floor(g[0]); eid = int(g[1]);
            elif m := re.fullmatch(r"OPEN-([BF]\d+)-(\d+)", content): event_type = "OPEN"; g = m.groups(); fl = str_to_floor(g[0]); eid = int(g[1]);
            elif m := re.fullmatch(r"CLOSE-([BF]\d+)-(\d+)", content): event_type = "CLOSE"; g = m.groups(); fl = str_to_floor(g[0]); eid = int(g[1]);
            elif m := re.fullmatch(r"RECEIVE-(\d+)-(\d+)", content): event_type = "RECEIVE"; g = m.groups(); pid = int(g[0]); eid = int(g[1]);
            elif m := re.fullmatch(r"IN-(\d+)-([BF]\d+)-(\d+)", content): event_type = "IN"; g = m.groups(); pid = int(g[0]); fl = str_to_floor(g[1]); eid = int(g[2]);
            elif m := re.fullmatch(r"OUT-([SF])-(\d+)-([BF]\d+)-(\d+)", content): event_type = "OUT"; g = m.groups(); flag = g[0]; pid = int(g[1]); fl = str_to_floor(g[2]); eid = int(g[3]);
            elif m := re.fullmatch(r"SCHE-BEGIN-(\d+)", content): event_type = "SCHE-BEGIN"; g = m.groups(); eid = int(g[0]);
            elif m := re.fullmatch(r"SCHE-END-(\d+)", content): event_type = "SCHE-END"; g = m.groups(); eid = int(g[0]);
            elif m := re.fullmatch(r"SCHE-ACCEPT-(\d+)-(\d+\.\d+)-([BF]\d+)", content): event_type = "SCHE-ACCEPT"; g = m.groups(); eid = int(g[0]); spd = float(g[1]); tfl = str_to_floor(g[2]);
            else: m = None # No match

            if m: # If any pattern matched
                 g = m.groups() # Get groups again safely
                 # Basic validation and structure creation
                 if event_type == "RECEIVE":
                     if pid not in self.passengers or not(1<=eid<=ELEVATOR_COUNT): raise ValueError("Invalid RECEIVE args")
                     parsed_event = {"type": event_type, "time": t, "person_id": pid, "elevator_id": eid}
                 elif event_type == "OUT":
                     if flag not in ['S', 'F'] or pid not in self.passengers or fl is None or not(1 <= eid <= ELEVATOR_COUNT): raise ValueError("Invalid OUT args")
                     parsed_event = {"type": event_type, "time": t, "success": flag == 'S', "person_id": pid, "floor": fl, "elevator_id": eid}
                 elif event_type in ["SCHE-BEGIN", "SCHE-END"]:
                     if not(1 <= eid <= ELEVATOR_COUNT): raise ValueError(f"Invalid {event_type} args")
                     parsed_event = {"type": event_type, "time": t, "elevator_id": eid}
                 elif event_type == "SCHE-ACCEPT":
                     if not(1 <= eid <= ELEVATOR_COUNT) or spd not in SCHE_VALID_SPEEDS or tfl is None or tfl not in SCHE_TARGET_FLOORS_SET: raise ValueError("Invalid SCHE-ACCEPT args")
                     parsed_event = {"type": event_type, "time": t, "elevator_id": eid, "speed": spd, "target_floor": tfl}
                 elif event_type in ["ARRIVE", "OPEN", "CLOSE"]:
                     if fl is None or not(1 <= eid <= ELEVATOR_COUNT): raise ValueError(f"Invalid {event_type} args")
                     parsed_event = {"type": event_type, "time": t, "floor": fl, "elevator_id": eid}
                 elif event_type == "IN":
                     if pid not in self.passengers or fl is None or not(1 <= eid <= ELEVATOR_COUNT): raise ValueError("Invalid IN args")
                     parsed_event = {"type": event_type, "time": t, "person_id": pid, "floor": fl, "elevator_id": eid}

        except (ValueError, IndexError, AttributeError) as e:
             errmsg = f"Error processing args for {event_type or 'Unknown Type'}: {e} (line: '{line}')"
             if not self.errors or errmsg not in self.errors[-1]: self.add_error(errmsg, t)
             return None
        except re.error as e_re:
             self.add_error(f"Regex error during parsing: {e_re} (line: '{line}')", t); return None

        if parsed_event is None:
             err_msg_unrec = f"Unrecognized output event format: '{content}' (line: '{line}')"
             if not self.errors or err_msg_unrec not in self.errors[-1]: self.add_error(err_msg_unrec, t)
        return parsed_event


    def validate_event(self, event):
        """Validates a single event based on HW6 rules and updates state (Corrected v11)."""
        if event is None: return False
        etype=event["type"]; t=event["time"]; eid=event.get("elevator_id")

        # Simplified Static Check remains
        is_static_at_event_start = False
        if eid and eid in self.elevators:
             is_static_at_event_start = (t >= self.elevators[eid].last_action_finish_time - EPSILON)

        if etype == "SCHE-ACCEPT":
            if eid is None or eid not in self.elevators: self.add_error(f"SCHE-ACCEPT invalid EID {eid}", t); return False
            el = self.elevators[eid]
            el.schedule_info={'accept_time':t, 'speed':event['speed'], 'target_floor':event['target_floor']}
            el.scheduling_state=ELEVATOR_SCHEDULING_PENDING; el.arrives_since_sche_accept=0; el.last_event_time=t;
            return True

        if eid is None or eid not in self.elevators: self.add_error(f"Event missing/invalid EID: {event}", t); return False
        el = self.elevators[eid]; el.last_event_time = t

        floor=event.get("floor"); pid=event.get("person_id"); p=self.passengers.get(pid) if pid else None
        fl_str=floor_to_str(floor) if floor is not None else "N/A"
        ds_str={0:"C", 1:"O"}.get(el.door_state, '?'); spd_used=el.current_speed
        is_sche_p=(el.scheduling_state==ELEVATOR_SCHEDULING_PENDING); is_sche_a=(el.scheduling_state==ELEVATOR_SCHEDULING_ACTIVE)

        try:
            # --- RECEIVE (Forbidden only during ACTIVE) ---
            if etype == "RECEIVE":
                if is_sche_a: self.add_error(f"RECEIVE-{pid}-{eid} during SCHE ACTIVE",t)
                if p is None: return False
                if p.state != PASSENGER_WAITING: self.add_error(f"RECEIVE-{pid}-{eid} P not WAITING ({p.state})",t)
                if p.received_by_elevator != -1: # Check if already received by *any* elevator
                     if p.received_by_elevator != eid: self.add_error(f"RECEIVE-{pid}-{eid} P already RcvdBy E{p.received_by_elevator}",t)
                     else: self.add_error(f"Duplicate RECEIVE-{pid}-{eid} without cancellation", t)
                p.received_by_elevator = eid; el.received_passengers.add(pid); return True

            # --- ARRIVE (Allowed during ACTIVE) ---
            elif etype == "ARRIVE":
                self.power_arrive += 1;
                if floor is None: return False
                if is_sche_p: el.arrives_since_sche_accept += 1
                if el.door_state == DOOR_OPEN: self.add_error(f"E{eid} ARRIVE @{fl_str} while door OPEN",t)
                exp_move_t = spd_used; exp_arr_t = el.last_action_finish_time + exp_move_t
                if t < exp_arr_t - EPSILON*20: self.add_error(f"E{eid} ARRIVE @{fl_str} too early. T:{t:.4f}<Exp:{exp_arr_t:.4f}(Last:{el.last_action_finish_time:.4f},Spd:{spd_used:.1f})",t)
                if floor not in VALID_FLOORS_SET: self.add_error(f"E{eid} ARRIVE invalid floor {fl_str}",t)
                else:
                    f_diff=abs(floor - el.current_floor); cross0=(el.current_floor * floor == -1 and abs(el.current_floor) == 1)
                    if not(f_diff == 1 or cross0) and floor != el.current_floor: self.add_error(f"E{eid} invalid move {floor_to_str(el.current_floor)}->{fl_str}",t)
                if el.passenger_count == 0 and not is_sche_a and not is_sche_p and not el.received_passengers:
                    self.add_error(f"E{eid} moved (ARRIVE {fl_str}) while seemingly idle/empty",t)
                el.current_floor = floor; el.action_completed(t); return True

            # --- OPEN (Forbidden during ACTIVE unless at target) ---
            elif etype == "OPEN":
                self.power_open += 1; floor = event["floor"]
                is_at_sche_target = is_sche_a and floor == el.schedule_info.get('target_floor')
                if is_sche_a and not is_at_sche_target: self.add_error(f"E{eid} OPEN @{fl_str} during SCHE ACTIVE (not target)",t)
                if el.door_state != DOOR_CLOSED: self.add_error(f"E{eid} OPEN @{fl_str} but door not C ({ds_str})",t)
                if floor != el.current_floor: self.add_error(f"E{eid} OPEN @ wrong floor {fl_str} (curr:{floor_to_str(el.current_floor)})",t)
                if t < el.last_action_finish_time - EPSILON*10: self.add_error(f"E{eid} OPEN @{fl_str} too early T:{t:.4f}<PrevFin:{el.last_action_finish_time:.4f}",t)
                el.door_state = DOOR_OPEN; el.action_completed(t); return True

            # --- CLOSE (Forbidden during ACTIVE unless at target) ---
            elif etype == "CLOSE":
                self.power_close += 1; floor = event["floor"]
                is_at_sche_target = is_sche_a and floor == el.schedule_info.get('target_floor')
                if is_sche_a and not is_at_sche_target: self.add_error(f"E{eid} CLOSE @{fl_str} during SCHE ACTIVE (not target)",t)
                if el.door_state != DOOR_OPEN: self.add_error(f"E{eid} CLOSE @{fl_str} but door not O ({ds_str})",t)
                if floor != el.current_floor: self.add_error(f"E{eid} CLOSE @ wrong floor {fl_str} (curr:{floor_to_str(el.current_floor)})",t)
                min_dur = SCHE_HOLD_TIME if is_at_sche_target else DOOR_TIME
                open_t = -1.0
                for i in range(len(self.events) - 1, -1, -1):
                    prev = self.events[i]
                    if prev.get('elevator_id') == eid and prev.get('floor') == floor:
                        if prev['type'] == 'OPEN': open_t = prev['time']; break
                        if prev['type'] == 'CLOSE': open_t = -2.0; break
                if open_t == -1.0: self.add_error(f"E{eid} CLOSE @{fl_str}: Cannot find corresponding OPEN event",t)
                elif open_t >= 0:
                    dur = t - open_t
                    if dur < min_dur - EPSILON*10: mode = "SCHE" if is_at_sche_target else "norm"; self.add_error(f"E{eid} door open @{fl_str} too short ({mode}):{dur:.4f}s<{min_dur:.1f}s (OpenT:{open_t:.4f})",t)
                el.door_state = DOOR_CLOSED; el.action_completed(t); return True

            # --- IN (Forbidden only during ACTIVE) ---
            elif etype == "IN":
                floor = event["floor"]; pid = event["person_id"]; p = self.passengers.get(pid)
                if floor is None or p is None: return False
                if is_sche_a: self.add_error(f"P{pid} IN E{eid} @{fl_str} during SCHE ACTIVE",t)
                if el.door_state != DOOR_OPEN: self.add_error(f"P{pid} IN E{eid} @{fl_str} door not O ({ds_str})",t)
                if el.passenger_count >= MAX_CAPACITY: self.add_error(f"E{eid} > capacity ({MAX_CAPACITY}) on IN P{pid} @{fl_str}",t)
                if floor != el.current_floor: self.add_error(f"P{pid} IN E{eid} @ wrong floor {fl_str} (E@ {floor_to_str(el.current_floor)})",t)
                if p.state != PASSENGER_WAITING: self.add_error(f"P{pid} IN E{eid} @{fl_str} but not WAITING (state={p.state})",t)
                elif floor != p.current_location: self.add_error(f"P{pid} IN E{eid} @{fl_str}, but P waiting @ {floor_to_str(p.current_location)}",t)
                if p.received_by_elevator != eid: self.add_error(f"P{pid} IN E{eid} @{fl_str}, but not RcvdBy it (RcvBy={p.received_by_elevator})",t)
                p.state = PASSENGER_INSIDE; p.current_elevator = eid; p.current_location = -999; p.received_by_elevator = -1
                if pid in el.received_passengers: el.received_passengers.remove(pid)
                if pid not in el.passengers: el.passengers.add(pid)
                else: self.add_error(f"P{pid} IN E{eid} but already inside", t)
                return True

            # --- OUT Validation (Corrected OUT-F check) ---
            elif etype == "OUT":
                succ = event["success"]; floor = event["floor"]; pid = event["person_id"]; p = self.passengers.get(pid)
                if floor is None or p is None: return False
                # OUT-F IS allowed even if not SCHE target floor, if doors happen to open (though opening might be invalid)
                # is_at_sche_target = is_sche_a and floor == el.schedule_info.get('target_floor')
                if el.door_state != DOOR_OPEN: self.add_error(f"P{pid} OUT E{eid} @{fl_str} door not O ({ds_str})",t)
                if floor != el.current_floor: self.add_error(f"P{pid} OUT E{eid} @ wrong floor {fl_str} (E@ {floor_to_str(el.current_floor)})",t)
                if p.state != PASSENGER_INSIDE or p.current_elevator != eid: self.add_error(f"P{pid} OUT E{eid} @{fl_str} but not INSIDE this E (st={p.state}, curE={p.current_elevator})",t)
                is_dest = (floor == p.to_floor)
                if succ and not is_dest: self.add_error(f"OUT-S P{pid} E{eid} @{fl_str} but not Dest ({floor_to_str(p.to_floor)})",t)
                if not succ and is_dest: self.add_error(f"OUT-F P{pid} E{eid} @ Dest {fl_str}. Should be OUT-S",t)
                # --- CORRECTED: Removed invalid OUT-F location check ---
                # if not succ and not is_at_sche_target: self.add_error(f"OUT-F P{pid} E{eid} @{fl_str} outside SCHE target arrival",t)
                p.current_elevator = -1; p.current_location = floor
                if pid in el.passengers: el.passengers.remove(pid)
                if succ: p.state = PASSENGER_ARRIVED; p.finish_time = t
                else: p.state = PASSENGER_WAITING
                p.received_by_elevator = -1
                if pid in el.received_passengers: el.received_passengers.remove(pid)
                return True

            # --- SCHE-BEGIN Validation (Corrected Static Check & RECEIVE Cancel Logic) ---
            elif etype == "SCHE-BEGIN":
                if not is_sche_p: self.add_error(f"SCHE-BEGIN E{eid} but not PENDING (state={el.scheduling_state})",t); return False
                s_info = el.schedule_info
                if el.arrives_since_sche_accept > 2: self.add_error(f"SCHE-BEGIN E{eid} after {el.arrives_since_sche_accept}>2 ARRIVEs (AcceptT:{s_info.get('accept_time',-1):.4f})",t)
                if el.door_state != DOOR_CLOSED: self.add_error(f"SCHE-BEGIN E{eid} door not C",t)
                if t < el.last_action_finish_time - EPSILON:
                     self.add_error(f"SCHE-BEGIN E{eid} while previous action not finished (T:{t:.4f} < PrevFin:{el.last_action_finish_time:.4f})",t)

                el.scheduling_state = ELEVATOR_SCHEDULING_ACTIVE
                el.current_speed = s_info.get('speed', MOVE_TIME_DEFAULT)
                el.schedule_info['begin_time'] = t

                # --- Explicitly Cancel RECEIVEs ---
                cancelled_passenger_ids = list(el.received_passengers)
                for rpid in cancelled_passenger_ids:
                    rp = self.passengers.get(rpid);
                    if rp and rp.received_by_elevator == eid:
                        rp.received_by_elevator = -1
                        # print(f"Debug: SCHE-BEGIN E{eid} cancelling Rcv for P{rpid} @{t:.2f}")
                el.received_passengers.clear();
                return True

            # --- SCHE-END Validation (Corrected State Check) ---
            elif etype == "SCHE-END":
                # --- CORRECTED State Check: Must be ACTIVE ---
                if not is_sche_a:
                     self.add_error(f"SCHE-END E{eid} but not ACTIVE (state={el.scheduling_state})",t);
                     return False
                # --- End Correction ---
                s_info = el.schedule_info; t_fl = s_info.get('target_floor')
                if t_fl is None: self.add_error(f"SCHE-END E{eid}: Internal Error - No target floor found",t)
                elif el.current_floor != t_fl: self.add_error(f"SCHE-END E{eid} @ wrong floor {floor_to_str(el.current_floor)} (Tgt:{floor_to_str(t_fl)})",t)

                if el.passenger_count > 0: self.add_error(f"SCHE-END E{eid} with {el.passenger_count} P inside",t)
                if el.door_state != DOOR_CLOSED: self.add_error(f"SCHE-END E{eid} door not C",t)

                acc_t = s_info.get('accept_time', -1.0)
                if acc_t < 0: self.add_error(f"SCHE-END E{eid}: Cannot find Accept time for current/last SCHE",t)
                else:
                    comp_t = t - acc_t;
                    if comp_t > SCHE_MAX_RESPONSE_TIME + EPSILON*10: self.add_error(f"SCHE E{eid} took too long: {comp_t:.4f}s>{SCHE_MAX_RESPONSE_TIME}s (AccT:{acc_t:.4f})",t)

                if t_fl is not None:
                    fnd_c=False; fnd_o=False; c_t=-1.0; o_t=-1.0; s_idx=len(self.events)-1
                    while s_idx >= 0:
                        prev=self.events[s_idx];
                        if prev.get('elevator_id')!=eid or prev.get('floor')!=t_fl: s_idx-=1; continue
                        if not fnd_c and prev['type']=='CLOSE':
                            fnd_c=True; c_t=prev['time'];
                            if t<c_t-EPSILON: self.add_error(f"SCHE-END E{eid} T:{t:.4f} < final CLOSE T:{c_t:.4f}",t)
                        elif fnd_c and not fnd_o and prev['type']=='OPEN':
                            fnd_o=True; o_t=prev['time']; hold=c_t-o_t;
                            if hold<SCHE_HOLD_TIME-EPSILON*10: self.add_error(f"SCHE hold E{eid}@{floor_to_str(t_fl)} short:{hold:.4f}s<{SCHE_HOLD_TIME}s",t)
                            break
                        elif fnd_c and prev['type'] not in ['OUT','OPEN']: break
                        s_idx -= 1
                    if not fnd_c or not fnd_o:
                         self.add_error(f"SCHE-END E{eid}: Cannot find valid OPEN/CLOSE({SCHE_HOLD_TIME}s+) sequence @ Tgt {floor_to_str(t_fl)}",t)

                el.scheduling_state = ELEVATOR_IDLE; el.current_speed = MOVE_TIME_DEFAULT; el.schedule_info = {};
                el.action_completed(t); return True

        except Exception as e:
             self.add_error(f"Internal validation error on event {event}: {e}",t)
             import traceback; self.add_error(f"Traceback: {traceback.format_exc()}",t); return False

        self.add_error(f"Unknown event type '{etype}' passed to validate_event",t); return False


    def validate_output(self, output_lines):
        """Main validation function for HW6."""
        # Reset state
        self.errors = []; self.events = []; self.last_global_time = 0.0
        self.power_arrive = 0; self.power_open = 0; self.power_close = 0; self.total_runtime = 0.0
        for el in self.elevators.values(): el.__init__(el.id)
        if not self.passengers and self.errors: return False
        elif not self.passengers and not output_lines: return True
        elif not self.passengers and output_lines: self.add_error("No requests, but output found"); return False
        for p in self.passengers.values(): p.__init__(p.id, p.priority, p.from_floor, p.to_floor, p.request_time)

        parsed_events_raw = []
        for line in output_lines:
            event = self.parse_output_line(line)
            if event: parsed_events_raw.append(event)
        parsed_events_raw.sort(key=lambda x: x['time'])

        self.events = []
        for event in parsed_events_raw:
            if self.validate_event(event):
                self.events.append(event)

        # Final State Checks (Removed finish_time < request_time check)
        print("\n--- Final State Check (HW6 v13) ---") # Update version
        final_errors = []
        all_p_ok = True
        if self.passengers:
            for pid, p in self.passengers.items():
                if p.state != PASSENGER_ARRIVED:
                    final_errors.append(f"P{pid} not ARRIVED (state={p.state})"); all_p_ok=False
            print(f"Passenger Check: {'OK' if all_p_ok else 'FAILED'}")
        else: print("Passenger Check: SKIPPED (No reqs)")

        all_e_ok = True
        for eid, el in self.elevators.items():
            if el.passenger_count > 0: final_errors.append(f"E{eid} end with P: {sorted(list(el.passengers))}"); all_e_ok=False
            if el.door_state != DOOR_CLOSED: final_errors.append(f"E{eid} end door not C (state={el.door_state})"); all_e_ok=False
            if el.scheduling_state != ELEVATOR_IDLE: final_errors.append(f"E{eid} end not IDLE (state={el.scheduling_state})"); all_e_ok=False
            if el.received_passengers: final_errors.append(f"E{eid} end with RcvP: {sorted(list(el.received_passengers))}"); all_e_ok=False
            if abs(el.current_speed - MOVE_TIME_DEFAULT) > EPSILON: final_errors.append(f"E{eid} end speed not default ({el.current_speed:.1f})"); all_e_ok=False
        print(f"Elevator Check: {'OK' if all_e_ok else 'FAILED'}")

        for msg in final_errors: self.add_error(f"Final State Error: {msg}")
        return not self.errors


    def calculate_performance(self, real_time):
        """Calculates HW6 performance metrics."""
        # (No changes from v12)
        t_run = max(real_time, self.total_runtime); wt = 0.0
        tot_wt_t = 0.0; tot_w = 0; finishers = 0
        if self.passengers:
            for p in self.passengers.values():
                if p.state == PASSENGER_ARRIVED and p.finish_time >= 0:
                    completion_time = p.finish_time - p.request_time
                    if completion_time >= 0:
                        tot_wt_t += completion_time * p.priority; tot_w += p.priority; finishers += 1
                elif p.id in self.passengers and p.state!=PASSENGER_ARRIVED: pass
            if tot_w > 0: wt = tot_wt_t / tot_w
            elif len(self.passengers) > 0 and finishers == 0: wt = float('inf'); print("Perf Error: No passengers finished correctly, WT=inf")
        power_w = (self.power_arrive * 0.4 + self.power_open * 0.1 + self.power_close * 0.1)
        return { "T_run": t_run, "WT": wt, "W": power_w,
                 "Arrives": self.power_arrive, "Opens": self.power_open, "Closes": self.power_close }