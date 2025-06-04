# run_test.py (v8 - Handle Timeout without stopping validation)
import subprocess
import time
import os
import sys
import random
import shutil
import concurrent.futures
import pathlib
import re
import traceback

# --- Imports ---
from generate_data import generate_requests_phased_hw6, ELEVATOR_COUNT, MAX_TOTAL_REQUESTS_MUTUAL, MAX_SCHE_REQUESTS_PUBLIC
from validator import OutputValidator

# Colorama setup
try:
    from colorama import init, Fore, Style
    init(autoreset=True); USE_COLOR = True
except ImportError:
    print("Colorama not found, output will be monochrome.")
    class DummyStyle:
        def __getattr__(self, name): return ""
    Fore = DummyStyle(); Style = DummyStyle(); USE_COLOR = False

# --- Configuration ---
BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATAPUT_EXE = BASE_DIR / "datainput_student_win64.exe"
JAVA_COMMAND = "java"
JAR_FILE = BASE_DIR / "code.jar"
OFFICIAL_JAR_FILE = BASE_DIR / "elevator2.jar"
MAIN_CLASS_NAME = "MainClass"
STDIN_FILENAME = "stdin.txt"
TIMEOUT_SECONDS_PUBLIC = 130
TIMEOUT_SECONDS_MUTUAL = 230
MAX_WORKERS = 10
TEST_SUBDIR_PREFIX = "test_run_"
RESULTS_DIR_NAME = "test_results_hw6"

# --- Helper ---
def print_color(text, color):
    if USE_COLOR: print(color + text + Style.RESET_ALL)
    else: print(text)

# --- Test Function ---
def run_single_test_parallel_subdir(test_index, test_config, base_path, results_path):
    status_code = "UNKNOWN"; performance_data = None; validation_errors = []
    stdout_lines = []; stderr_output = ""; real_time_taken = 0; java_exit_code = -1
    test_type = test_config['type']
    timeout_seconds = TIMEOUT_SECONDS_MUTUAL if test_type == 'mutual' else TIMEOUT_SECONDS_PUBLIC
    # --- 新增: 超时标志 ---
    timed_out = False

    test_subdir_path = base_path / f"{TEST_SUBDIR_PREFIX}{test_index}_{test_type}"
    try:
        test_subdir_path.mkdir(exist_ok=True)

        required_files = [DATAPUT_EXE, JAR_FILE, OFFICIAL_JAR_FILE]
        for f in required_files:
            if f.exists(): shutil.copy2(f, test_subdir_path / f.name)
            else: raise FileNotFoundError(f"Required file not found: {f}")

        local_stdin_path = test_subdir_path / STDIN_FILENAME
        print(f"[Test {test_index} ({test_type})] Generating data ({test_config['passenger_reqs']} P, {test_config['sche_reqs']} S)...")
        if not generate_requests_phased_hw6(
            num_passenger_requests=test_config['passenger_reqs'],
            num_sche_requests=test_config['sche_reqs'],
            filename=local_stdin_path, is_mutual_test=(test_type == 'mutual')
        ):
            status_code = "FAIL_GENERATE"; raise RuntimeError("Data generation failed.")

        classpath_sep = ";" if os.name == 'nt' else ":"
        classpath = f'"{JAR_FILE.name}"{classpath_sep}"{OFFICIAL_JAR_FILE.name}"'
        cmd = f'.\\{DATAPUT_EXE.name} | {JAVA_COMMAND} -cp {classpath} {MAIN_CLASS_NAME}'

        print(f"[Test {test_index} ({test_type})] Executing (Timeout: {timeout_seconds}s)...")
        start_time = time.time()
        process = None
        try:
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding='utf-8', errors='replace', cwd=test_subdir_path)
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            end_time = time.time(); real_time_taken = end_time - start_time
            stdout_lines = stdout.splitlines() if stdout else []; stderr_output = stderr if stderr else ""
            java_exit_code = process.returncode

            print(f"[Test {test_index} ({test_type})] Execution finished in {real_time_taken:.2f}s (Java Exit: {java_exit_code}).")
            if stderr_output.strip():
                status_code = "FAIL_STDERR_OUTPUT"
                print_color(f"[Test {test_index} ({test_type})] Error: Non-empty stderr output detected!", Fore.RED)
            elif java_exit_code != 0:
                 status_code = "FAIL_JAVA_ERROR"
                 print_color(f"[Test {test_index} ({test_type})] Java process exited with error code: {java_exit_code}", Fore.YELLOW)
            else:
                status_code = "EXECUTION_COMPLETE"

        except subprocess.TimeoutExpired:
            end_time = time.time(); real_time_taken = end_time - start_time
            print_color(f"[Test {test_index} ({test_type})] Error: Process timed out after {timeout_seconds}s.", Fore.RED)
            # --- 修改: 记录超时，但不立即失败 ---
            timed_out = True
            status_code = "EXECUTION_TIMED_OUT" # 用一个临时的状态码
            if process:
                process.kill()
                try:
                    # 尝试获取超时前的输出
                    stdout, stderr = process.communicate(timeout=1) # 短暂等待获取残余输出
                    stdout_lines = stdout.splitlines() if stdout else []
                    stderr_output = stderr if stderr else ""
                except Exception as e_comm_timeout:
                     # 如果获取输出也超时或失败，记录下来
                     stderr_output += f"\n--- Error getting output after timeout kill: {e_comm_timeout} ---"
            # --- 修改结束 ---

        except Exception as e_exec:
            # ... (保持不变) ...
            end_time = time.time(); real_time_taken = end_time - start_time
            print_color(f"[Test {test_index} ({test_type})] Error during execution: {e_exec}", Fore.RED)
            if process: process.kill()
            status_code = "FAIL_RUNTIME"; stderr_output += f"\n--- Python Execution Error ---\n{e_exec}"


        # --- 验证步骤照常进行 (即使可能超时) ---
        validation_success = False
        if status_code != "FAIL_STDERR_OUTPUT": # 只有在stderr干净时才验证
            print(f"[Test {test_index} ({test_type})] Validating output (Timed Out: {timed_out})...")
            try:
                validator = OutputValidator(local_stdin_path)
                validation_success = validator.validate_output(stdout_lines)
                validation_errors.extend(validator.errors) # 使用 extend 合并错误
            except Exception as e_val:
                validation_success = False
                validation_errors.append(f"Error during validation itself: {e_val}")
                validation_errors.append(traceback.format_exc())
        else:
            validation_errors = ["Stderr was not empty. Validation skipped."]


        # --- 最终状态判断 (优先考虑超时) ---
        final_status = "UNKNOWN"
        if timed_out:
            final_status = "FAIL_TIMEOUT" # 超时是最终的失败原因
            print_color(f"[Test {test_index} ({test_type})] Failed! Reason: {final_status} (Validation ran on partial output)", Fore.RED)
        elif validation_success and status_code == "EXECUTION_COMPLETE":
            final_status = "PASS"
            performance_data = validator.calculate_performance(real_time_taken)
            print_color(f"[Test {test_index} ({test_type})] Passed.", Fore.GREEN)
        else:
            # 如果没超时，按原来的逻辑判断失败原因
            if status_code.startswith("FAIL"): final_status = status_code
            elif not validation_success: final_status = "FAIL_VALIDATE"
            else: final_status = "FAIL_UNKNOWN" # Should not happen normally
            print_color(f"[Test {test_index} ({test_type})] Failed! Reason: {final_status}", Fore.RED)

        # --- 保存失败日志 (如果最终状态不是 PASS) ---
        if final_status != "PASS":
            failed_data_filename = results_path / f"failed_data_{test_index}_{test_type}.txt"
            failed_stdout_filename = results_path / f"failed_stdout_{test_index}_{test_type}.txt"
            # print(f"[Test {test_index}] Saving failed input to {failed_data_filename.relative_to(base_path)}") # Verbose
            try: shutil.copyfile(local_stdin_path, failed_data_filename)
            except Exception as e_copy: print_color(f"  [T{test_index}] Warning: Error copying input: {e_copy}", Fore.YELLOW)
            # print(f"[Test {test_index}] Saving failed output/log to {failed_stdout_filename.relative_to(base_path)}") # Verbose
            try:
                with open(failed_stdout_filename, "w", encoding='utf-8', errors='replace') as f:
                     # 添加更多调试信息，包括超时标志
                     f.write(f"--- TEST INFO ---\nIndex: {test_index}\nType: {test_type}\nFinal Status: {final_status}\nTimed Out: {timed_out}\nExecution Status Code: {status_code}\nReal Time: {real_time_taken:.3f}s\nJava Exit Code: {java_exit_code}\n")
                     f.write("\n--- STDIN ---\n");
                     try:
                         with open(local_stdin_path, "r", encoding='utf-8') as sf: f.write(sf.read())
                     except Exception as e_read_stdin: f.write(f"Error reading stdin: {e_read_stdin}\n")
                     f.write("\n\n--- STDOUT (Partial if Timed Out) ---\n"); f.write("\n".join(stdout_lines))
                     f.write("\n\n--- STDERR ---\n"); f.write(stderr_output)
                     if validation_errors:
                         f.write("\n\n--- Validation Errors ---\n")
                         for v_err in validation_errors: f.write(f"{v_err}\n")
            except IOError as e_write: print_color(f"  [T{test_index}] Warning: Error writing failure log: {e_write}", Fore.YELLOW)


    except FileNotFoundError as e_fnf:
         print_color(f"[Test {test_index} ({test_type})] Error: Setup failed: {e_fnf}", Fore.RED)
         final_status = "FAIL_SETUP"; validation_errors.append(f"Setup Error: {e_fnf}")
    except Exception as e_outer:
         print_color(f"[Test {test_index} ({test_type})] Error in test wrapper: {e_outer}", Fore.RED)
         final_status = "FAIL_WRAPPER_ERROR";
         tb_str = traceback.format_exc(); print(f"Traceback:\n{tb_str}")
         wrapper_error_msg = f"Wrapper Error: {e_outer}\nTraceback:\n{tb_str}"
         validation_errors.append(wrapper_error_msg); stderr_output += f"\n--- Python Wrapper Error ---\n{wrapper_error_msg}"
    finally:
        try:
            if test_subdir_path.exists(): shutil.rmtree(test_subdir_path)
        except Exception as e_clean: print_color(f"[Test {test_index}] Warning: Failed to clean up subdir: {e_clean}", Fore.YELLOW)

    return {"index": test_index, "type": test_type, "status": final_status, "performance": performance_data,
            "errors": validation_errors, "stderr": stderr_output, "real_time_taken": real_time_taken}


# --- Main Execution Logic ---
if __name__ == "__main__":
    # (模式选择和测试数量获取逻辑不变)
    test_mode_choice = ""; test_mode = ""
    while test_mode_choice not in ['1', '2']:
        test_mode_choice = input("请选择测试模式 (输入数字):\n  1: 公测 (Public) 模式\n  2: 互测 (Mutual) 模式\n选择: ")
        if test_mode_choice == '1': test_mode = 'public'
        elif test_mode_choice == '2': test_mode = 'mutual'
        else: print_color("无效输入，请输入 1 或 2。", Fore.RED)
    print_color(f"\n已选择模式: {test_mode.capitalize()}", Style.BRIGHT)
    total_test_cases = 0
    while True:
        try:
            num_input = input(f"请输入要运行的 {test_mode.capitalize()} 测试点数量 (必须是 {MAX_WORKERS} 的倍数): ")
            total_test_cases = int(num_input)
            if total_test_cases > 0 and total_test_cases % MAX_WORKERS == 0: break
            else: print_color(f"输入必须是大于 0 且是 {MAX_WORKERS} 的倍数。", Fore.RED)
        except ValueError: print_color("请输入一个整数。", Fore.RED)

    # 清理旧的结果目录
    results_dir_path = BASE_DIR / RESULTS_DIR_NAME
    if results_dir_path.exists():
        print(f"\n正在删除旧的结果目录: {RESULTS_DIR_NAME}...")
        try: shutil.rmtree(results_dir_path)
        except Exception as e_clean_res: print_color(f"警告: 删除旧结果目录 {RESULTS_DIR_NAME} 时出错: {e_clean_res}", Fore.YELLOW)
    results_dir_path.mkdir(exist_ok=True)

    print("\n清理旧的测试子目录...")
    for item in BASE_DIR.glob(f"{TEST_SUBDIR_PREFIX}*"):
        if item.is_dir():
            try: shutil.rmtree(item)
            except Exception as e_clean_old: print_color(f"  Warning: 无法移除旧目录 {item.name}: {e_clean_old}", Fore.YELLOW)

    # 检查必要文件
    essential_files = [DATAPUT_EXE, JAR_FILE, OFFICIAL_JAR_FILE]
    if not all(f.exists() for f in essential_files):
        print_color(f"错误: 缺少必要文件 (datainput, {JAR_FILE.name}, {OFFICIAL_JAR_FILE.name}). 中止测试。", Fore.RED); sys.exit(1)

    overall_start_time = time.time(); all_results = []; tests_completed_count = 0

    # 配置测试参数
    test_configs_to_run = []
    print(f"\n准备 {total_test_cases} 个 {test_mode.capitalize()} 测试配置...")
    for i in range(total_test_cases):
        config = {'type': test_mode}
        if test_mode == 'public':
            config['passenger_reqs'] = random.randint(80, 100)
            config['sche_reqs'] = random.randint(15, MAX_SCHE_REQUESTS_PUBLIC)
        else: # mutual
            p_req = random.randint(50, 65)
            s_req = min(random.randint(3, 8), MAX_TOTAL_REQUESTS_MUTUAL - p_req, ELEVATOR_COUNT)
            config['passenger_reqs'] = p_req; config['sche_reqs'] = s_req
        test_configs_to_run.append(config)

    total_tests_to_run = len(test_configs_to_run)
    print(f"\n开始 {total_tests_to_run} 个 {test_mode.capitalize()} 测试 (批次大小: {MAX_WORKERS})...")

    # 运行测试批次
    while tests_completed_count < total_tests_to_run:
        current_batch_start_index = tests_completed_count + 1
        num_tests_in_batch = min(MAX_WORKERS, total_tests_to_run - tests_completed_count)
        current_batch_end_index = current_batch_start_index + num_tests_in_batch - 1
        print(f"\n--- 运行批次: 测试 {current_batch_start_index} 到 {current_batch_end_index} ({test_mode.capitalize()}) ---")
        batch_start_time = time.time(); futures = []; batch_results_temp = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i in range(num_tests_in_batch):
                test_case_index = current_batch_start_index + i
                test_config = test_configs_to_run[tests_completed_count + i]
                future = executor.submit(run_single_test_parallel_subdir, test_case_index, test_config, BASE_DIR, results_dir_path)
                futures.append(future)

            print(f"等待批次 (测试 {current_batch_start_index}-{current_batch_end_index}) 完成...")
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result(); batch_results_temp.append(result)
                    status_color = Fore.GREEN if result.get('status') == 'PASS' else Fore.RED
                    print_color(f"  测试 {result.get('index', '?')} ({result.get('type','?')}) 完成状态: {result.get('status', 'UNKNOWN')}", status_color)
                    if result.get('status') == 'PASS':
                        perf = result.get('performance')
                        if perf:
                            print(f"    性能 (测试 {result.get('index')}) - 实时: {result.get('real_time_taken', -1.0):.3f}s:")
                            t_run=perf.get('T_run',float('inf')); wt=perf.get('WT',float('inf')); w=perf.get('W',float('inf'))
                            wt_s=f"{wt:.3f}" if wt!=float('inf') else "Inf"; w_s=f"{w:.2f}" if w!=float('inf') else "Inf"
                            print(f"      T_run:{t_run:.3f}s, WT:{wt_s}, W:{w_s} (Arr:{perf.get('Arrives',0)}, Op:{perf.get('Opens',0)}, Cl:{perf.get('Closes',0)})")
                except Exception as e_future:
                    print_color(f"检索测试结果时出错: {e_future}", Fore.RED)
                    err_idx = f"{current_batch_start_index + len(batch_results_temp)}?"; tb_str_future = traceback.format_exc()
                    batch_results_temp.append({"index":err_idx,"type":test_mode,"status":"FAIL_FUTURE_ERROR","errors":[f"Future Error: {e_future}\n{tb_str_future}"],"stderr":"","real_time_taken":-1})

        batch_end_time = time.time()
        print(f"--- 批次完成于 {batch_end_time - batch_start_time:.2f} 秒 ---")
        all_results.extend(batch_results_temp); tests_completed_count += num_tests_in_batch

    overall_end_time = time.time()
    print(f"\n所有 {total_tests_to_run} 个测试完成。总执行时间: {overall_end_time - overall_start_time:.2f} 秒。")

    # --- Final Summary ---
    total_passed_count = 0; total_failed_tests_summary = []
    all_results.sort(key=lambda x: x.get("index", float('inf')))
    for result in all_results:
        if result.get('status') == "PASS": total_passed_count += 1
        else: total_failed_tests_summary.append(result)

    print("\n" + "="*20 + f" 最终测试总结 (HW6 - 模式: {test_mode.capitalize()}) " + "="*20)
    print_color(f"总执行测试数: {len(all_results)}", Style.BRIGHT)
    print_color(f"通过: {total_passed_count}", Fore.GREEN)
    failed_count = len(total_failed_tests_summary)
    print_color(f"失败: {failed_count}", Fore.RED if failed_count > 0 else Fore.WHITE)

    if total_failed_tests_summary:
        print("\n--- 失败测试详情 ---")
        reason_map = { "FAIL_VALIDATE": "验证错误", "FAIL_TIMEOUT": "超时", # Timeout is now primary failure reason
                       "FAIL_RUNTIME": "运行时错误", "FAIL_JAVA_ERROR": "Java错误(非0退出)",
                       "FAIL_STDERR_OUTPUT": "Stderr非空", "FAIL_GENERATE": "数据生成错误",
                       "FAIL_SETUP": "设置错误", "FAIL_WRAPPER_ERROR": "包装器错误(见日志)",
                       "FAIL_FUTURE_ERROR": "并行错误(见日志)", "FAIL_UNKNOWN": "未知" }
        for failure in total_failed_tests_summary:
             idx = failure.get("index", "?"); ftype = failure.get("type", "?"); code = failure.get("status", "FAIL_UNKNOWN")
             reason_str = reason_map.get(code, code)
             print_color(f"  测试 {idx} ({ftype}): {reason_str}", Fore.RED)
             print(f"      输入:  {results_dir_path.name}{os.sep}failed_data_{idx}_{ftype}.txt")
             print(f"      输出/日志: {results_dir_path.name}{os.sep}failed_stdout_{idx}_{ftype}.txt")
             errors = failure.get("errors", [])
             # Display relevant error snippet
             if code == "FAIL_TIMEOUT": print(f"      超时时间: {TIMEOUT_SECONDS_MUTUAL if ftype=='mutual' else TIMEOUT_SECONDS_PUBLIC}s")
             elif code in ["FAIL_WRAPPER_ERROR", "FAIL_FUTURE_ERROR"]:
                  tb_lines = [line for line in errors if "Traceback" in line]
                  if tb_lines: print(f"      关键错误: {tb_lines[0][:150]}...")
                  elif errors: print(f"      关键错误: {errors[0][:100]}...")
             elif code == "FAIL_STDERR_OUTPUT": print(f"      Stderr 内容: ... {failure.get('stderr','').strip()[-100:]}")
             elif errors: print(f"      关键错误: {errors[0][:100]}...")
             elif failure.get('stderr'): # If no validation error but stderr exists
                 lines = [line for line in failure['stderr'].splitlines() if line.strip()]
                 if lines: print(f"      Stderr 提示: ...{lines[-1][-100:]}")


    print("="* (50 + len(test_mode)))
    print(f"\n测试运行完成。请检查 '{RESULTS_DIR_NAME}' 目录获取失败详情。")