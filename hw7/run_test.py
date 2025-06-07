import subprocess
import time
import os
import sys
import random
import shutil
import concurrent.futures
import pathlib
import traceback

from generate_data import generate_requests_phased_hw7, ELEVATOR_COUNT, MAX_TOTAL_REQUESTS_MUTUAL, MAX_UPDATE_REQUESTS, MAX_SCHE_REQUESTS_PUBLIC
from validator import OutputValidator

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    USE_COLOR = True
except ImportError:
    print("未找到 Colorama, 输出将为单色.")
    class DummyStyle:
        def __getattr__(self, name):
            return ""
    Fore = DummyStyle()
    Style = DummyStyle()
    USE_COLOR = False

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATAPUT_EXE = BASE_DIR / "datainput_student_win64.exe"
JAVA_COMMAND = "java"; JAR_FILE = BASE_DIR / "code.jar"
OFFICIAL_JAR_FILE = BASE_DIR / "elevator3.jar"; MAIN_CLASS_NAME = "MainClass"
STDIN_FILENAME = "stdin.txt"; TIMEOUT_SECONDS_PUBLIC = 180 # 使用调整后的公测超时
TIMEOUT_SECONDS_MUTUAL = 220; MAX_WORKERS = 10
TEST_SUBDIR_PREFIX = "test_run_"; RESULTS_DIR_NAME = "test_results_hw7"

def print_color(text, color):
    if USE_COLOR:
        print(color + text + Style.RESET_ALL)
    else:
        print(text)

def run_single_test_parallel_subdir(test_index, test_config, base_path, results_path):
    status_code = "UNKNOWN"; performance_data = None; validation_errors = []
    stdout_lines = []; stderr_output = ""; real_time_taken = 0; java_exit_code = -1
    test_type = test_config['type']
    timeout_seconds = TIMEOUT_SECONDS_MUTUAL if test_type == 'mutual' else TIMEOUT_SECONDS_PUBLIC
    timed_out = False
    test_subdir_path = base_path / f"{TEST_SUBDIR_PREFIX}{test_index}_{test_type}"
    final_status = "UNKNOWN"

    try:
        test_subdir_path.mkdir(exist_ok=True)
        required_files = [DATAPUT_EXE, JAR_FILE, OFFICIAL_JAR_FILE]
        for f in required_files:
            if f.exists():
                shutil.copy2(f, test_subdir_path / f.name)
            else:
                raise FileNotFoundError(f"必需文件未找到: {f}")

        local_stdin_path = test_subdir_path / STDIN_FILENAME
        print(f"[测试 {test_index} ({test_type})] 生成数据 ({test_config['passenger_reqs']} P, {test_config['sche_reqs']} S, {test_config['update_reqs']} U)...")
        if not generate_requests_phased_hw7(
            num_passenger_requests=test_config['passenger_reqs'],
            num_sche_requests=test_config['sche_reqs'],
            num_update_requests=test_config['update_reqs'],
            filename=local_stdin_path, is_mutual_test=(test_type == 'mutual')
        ):
            status_code = "FAIL_GENERATE"
            raise RuntimeError("数据生成失败.")

        classpath_sep = ";" if os.name == 'nt' else ":"
        classpath = f'"{JAR_FILE.name}"{classpath_sep}"{OFFICIAL_JAR_FILE.name}"'
        cmd = f'.\\{DATAPUT_EXE.name} | {JAVA_COMMAND} -cp {classpath} {MAIN_CLASS_NAME}'

        print(f"[测试 {test_index} ({test_type})] 执行程序 (超时: {timeout_seconds}s)...")
        start_time = time.time()
        process = None
        stdout = None
        stderr = None
        try:
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding='utf-8', errors='replace', cwd=test_subdir_path)
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            end_time = time.time()
            real_time_taken = end_time - start_time
            stdout_lines = stdout.splitlines() if stdout else []
            stderr_output = stderr if stderr else ""
            java_exit_code = process.returncode
            print(f"[测试 {test_index} ({test_type})] 执行完成于 {real_time_taken:.2f}s (Java 退出码: {java_exit_code}).")
            if stderr_output.strip():
                status_code = "FAIL_STDERR_OUTPUT"
            elif java_exit_code != 0:
                 status_code = "FAIL_JAVA_ERROR"
            else:
                status_code = "EXECUTION_COMPLETE"
        except subprocess.TimeoutExpired:
            end_time = time.time()
            real_time_taken = end_time - start_time
            print_color(f"[测试 {test_index} ({test_type})] 错误: 进程超时 {timeout_seconds}s.", Fore.RED)
            timed_out = True
            status_code = "EXECUTION_TIMED_OUT"
            if process:
                process.kill()
                stdout_after_kill = None
                stderr_after_kill = None
                try:
                    stdout_after_kill, stderr_after_kill = process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    print_color(f"  [T{test_index}] 信息: 获取残余输出超时 (1s)，可能进程未能完全终止。", Fore.CYAN)
                except Exception as e_comm_kill:
                    print_color(f"  [T{test_index}] 警告: kill 后 communicate 出错: {e_comm_kill}", Fore.YELLOW)
                    stderr_output += f"\n--- Error in communicate after kill: {e_comm_kill} ---"

                if stdout_after_kill is not None:
                     stdout_lines = stdout_after_kill.splitlines()
                if stderr_after_kill is not None:
                     stderr_output = stderr_after_kill
        except Exception as e_exec:
            end_time = time.time()
            real_time_taken = end_time - start_time
            print_color(f"[测试 {test_index} ({test_type})] 执行期间出错: {e_exec}", Fore.RED)
            if process:
                process.kill()
            status_code = "FAIL_RUNTIME"
            stderr_output += f"\n--- Python 执行错误 ---\n{e_exec}"

        validation_success = False
        first_validation_errors = []
        if status_code != "FAIL_STDERR_OUTPUT":
            print(f"[测试 {test_index} ({test_type})] 第一次验证输出...")
            try:
                validator = OutputValidator(local_stdin_path)
                validation_success = validator.validate_output(stdout_lines)
                first_validation_errors.extend(validator.errors)
                validation_errors.extend(first_validation_errors)
            except Exception as e_val:
                 validation_success = False
                 err_msg = f"第一次验证崩溃: {e_val}\n{traceback.format_exc()}"
                 validation_errors.append(err_msg)
                 first_validation_errors.append(err_msg)
        else:
            validation_errors = ["Stderr 非空，跳过验证。"]
            first_validation_errors = validation_errors[:]

        initial_status = "UNKNOWN"
        if status_code == "EXECUTION_TIMED_OUT":
            initial_status = "FAIL_TIMEOUT"
        elif validation_success and status_code == "EXECUTION_COMPLETE":
            initial_status = "PASS"
        else:
            if status_code.startswith("FAIL"):
                initial_status = status_code
            elif not validation_success:
                initial_status = "FAIL_VALIDATE"
            else:
                initial_status = "FAIL_UNKNOWN"

        performance_data = None
        final_status = initial_status

        if initial_status == "PASS" and not timed_out:
            print(f"[测试 {test_index} ({test_type})] 重新验证以计算性能...")
            try:
                perf_validator = OutputValidator(local_stdin_path)
                revalidation_success = perf_validator.validate_output(stdout_lines)
                revalidation_errors = perf_validator.errors

                if revalidation_success:
                    print(f"[测试 {test_index} ({test_type})] 重新验证成功，计算性能...")
                    performance_data = perf_validator.calculate_performance(real_time_taken)
                else:
                    print_color(f"  [T{test_index}] 警告: 性能计算前重新验证失败。", Fore.YELLOW)
                    final_status = "FAIL_VALIDATE_RECHECK" # 更新最终状态
                    validation_errors.extend(["--- 性能计算前重新验证失败 ---"])
                    validation_errors.extend(revalidation_errors)
                    if revalidation_errors:
                        print_color(f"    重新验证错误详情 ({len(revalidation_errors)} 条):", Fore.YELLOW)
                        for err in revalidation_errors:
                            print_color(f"      {err}", Fore.YELLOW)
            except Exception as e_perf:
                print_color(f"  [T{test_index}] 警告: 计算性能时出错: {e_perf}", Fore.YELLOW)
                final_status = "FAIL_PERF_CALC_ERROR"
                validation_errors.append(f"计算性能时出错: {e_perf}\n{traceback.format_exc()}")

        print_color(f"[测试 {test_index} ({test_type})] 最终结果: {final_status}", Fore.GREEN if final_status == "PASS" else Fore.RED)

        if final_status != "PASS":
             failed_data_filename = results_path / f"failed_data_{test_index}_{test_type}.txt"
             failed_stdout_filename = results_path / f"failed_stdout_{test_index}_{test_type}.txt"
             try:
                 shutil.copyfile(local_stdin_path, failed_data_filename)
             except Exception as e_copy:
                 print_color(f"  [T{test_index}] 警告: 复制输入失败: {e_copy}", Fore.YELLOW)
             try:
                 with open(failed_stdout_filename, "w", encoding='utf-8', errors='replace') as f:
                      f.write(f"--- TEST INFO HW7 ---\nIndex: {test_index}\nType: {test_type}\nFinal Status: {final_status}\nTimed Out: {timed_out}\nReal Time: {real_time_taken:.3f}s\nJava Exit Code: {java_exit_code}\n")
                      f.write("\n--- STDIN ---\n");
                      try:
                          with open(local_stdin_path, "r", encoding='utf-8') as sf: f.write(sf.read())
                      except Exception as e_read_stdin: f.write(f"读取 stdin 失败: {e_read_stdin}\n")
                      f.write("\n\n--- STDOUT (可能部分) ---\n"); f.write("\n".join(stdout_lines))
                      f.write("\n\n--- STDERR ---\n"); f.write(stderr_output)
                      if validation_errors: f.write("\n\n--- Validation Errors ---\n"); f.write("\n".join(validation_errors))
             except IOError as e_write: print_color(f"  [T{test_index}] 警告: 写入失败日志失败: {e_write}", Fore.YELLOW)

    except Exception as e_outer:
         print_color(f"[测试 {test_index} ({test_type})] 包装器错误: {e_outer}", Fore.RED)
         final_status = "FAIL_WRAPPER_ERROR" # 确保设置 final_status
         tb_str = traceback.format_exc(); print(f"Traceback:\n{tb_str}")
         validation_errors.append(f"包装器错误: {e_outer}\n{tb_str}")
    finally:
        try:
            if test_subdir_path.exists(): shutil.rmtree(test_subdir_path)
        except Exception as e_clean: print_color(f"[测试 {test_index}] 警告: 清理子目录失败: {e_clean}", Fore.YELLOW)

    return {"index": test_index, "type": test_type, "status": final_status, "performance": performance_data,
            "errors": validation_errors, "stderr": stderr_output, "real_time_taken": real_time_taken}

if __name__ == "__main__":
    test_mode_choice = ""; test_mode = ""
    while test_mode_choice not in ['1', '2']:
        test_mode_choice = input("请选择测试模式 (输入数字):\n  1: 公测 (Public) 模式\n  2: 互测 (Mutual) 模式\n选择: ")
        if test_mode_choice == '1':
            test_mode = 'public'
        elif test_mode_choice == '2':
            test_mode = 'mutual'
        else:
            print_color("无效输入，请输入 1 或 2。", Fore.RED)
    if not test_mode: sys.exit(1)
    print_color(f"\n已选择模式: {test_mode.capitalize()} for HW7", Style.BRIGHT)

    total_test_cases = 0
    while True:
        try:
            num_input = input(f"请输入要运行的 {test_mode.capitalize()} 测试点数量 (必须是 {MAX_WORKERS} 的倍数): ")
            total_test_cases = int(num_input)
            if total_test_cases > 0 and total_test_cases % MAX_WORKERS == 0: break
            else: print_color(f"输入必须是大于 0 且是 {MAX_WORKERS} 的倍数。", Fore.RED)
        except ValueError: print_color("请输入一个整数。", Fore.RED)

    results_dir_path = BASE_DIR / RESULTS_DIR_NAME
    if results_dir_path.exists(): print(f"\n正在删除旧的结果目录: {RESULTS_DIR_NAME}..."); shutil.rmtree(results_dir_path, ignore_errors=True)
    results_dir_path.mkdir(exist_ok=True); print("\n清理旧的测试子目录...");
    for item in BASE_DIR.glob(f"{TEST_SUBDIR_PREFIX}*"):
        if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
    essential_files = [DATAPUT_EXE, JAR_FILE, OFFICIAL_JAR_FILE];
    if not all(f.exists() for f in essential_files): print_color(f"错误: 缺少必需文件. 中止测试。", Fore.RED); sys.exit(1)

    overall_start_time = time.time(); all_results = []; tests_completed_count = 0

    test_configs_to_run = []
    print(f"\n准备 {total_test_cases} 个 {test_mode.capitalize()} HW7 测试配置...")
    for i in range(total_test_cases):
        config = {'type': test_mode}
        if test_mode == 'public':
            config['passenger_reqs'] = random.randint(85, 100)
            config['sche_reqs'] = random.randint(3, MAX_SCHE_REQUESTS_PUBLIC)
            config['update_reqs'] = random.choice([2, 3])
            config['update_reqs'] = min(config['update_reqs'], MAX_UPDATE_REQUESTS)
        else:
            p_req = random.randint(50, 65)
            u_req = random.randint(1, min(MAX_UPDATE_REQUESTS, 3))
            s_req = min(random.randint(1, 3), MAX_TOTAL_REQUESTS_MUTUAL - p_req - u_req, ELEVATOR_COUNT - u_req*2)
            s_req = max(0, s_req)
            p_req = max(1, MAX_TOTAL_REQUESTS_MUTUAL - u_req - s_req)
            config['passenger_reqs'] = p_req; config['sche_reqs'] = s_req; config['update_reqs'] = u_req;
        test_configs_to_run.append(config)

    total_tests_to_run = len(test_configs_to_run)
    print(f"\n开始 {total_tests_to_run} 个 {test_mode.capitalize()} HW7 测试 (批次大小: {MAX_WORKERS})...")

    while tests_completed_count < total_tests_to_run:
        current_batch_start_index = tests_completed_count + 1; num_tests_in_batch = min(MAX_WORKERS, total_tests_to_run - tests_completed_count)
        current_batch_end_index = current_batch_start_index + num_tests_in_batch - 1; print(f"\n--- 运行批次: 测试 {current_batch_start_index} 到 {current_batch_end_index} ({test_mode.capitalize()} HW7) ---")
        batch_start_time = time.time(); futures = []; batch_results_temp = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i in range(num_tests_in_batch):
                test_case_index = current_batch_start_index + i; test_config = test_configs_to_run[tests_completed_count + i]
                future = executor.submit(run_single_test_parallel_subdir, test_case_index, test_config, BASE_DIR, results_dir_path); futures.append(future)
            print(f"等待批次 (测试 {current_batch_start_index}-{current_batch_end_index}) 完成...")
            for future in concurrent.futures.as_completed(futures):
                 try:
                    result = future.result(); batch_results_temp.append(result)
                    status_color = Fore.GREEN if result.get('status') == 'PASS' else Fore.RED; print_color(f"  测试 {result.get('index', '?')} ({result.get('type','?')}) 完成，最终状态: {result.get('status', 'UNKNOWN')}", status_color)
                    if result.get('status') == 'PASS':
                        perf = result.get('performance');
                        if perf: print(f"    性能 (测试 {result.get('index')}) - 实时: {result.get('real_time_taken', -1.0):.3f}s:"); t_run=perf.get('T_run',float('inf')); wt=perf.get('WT',float('inf')); w=perf.get('W',float('inf')); wt_s=f"{wt:.3f}" if wt!=float('inf') else "Inf"; w_s=f"{w:.2f}" if w!=float('inf') else "Inf"; print(f"      T_run:{t_run:.3f}s, WT:{wt_s}, W:{w_s} (Arr:{perf.get('Arrives',0)}, Op:{perf.get('Opens',0)}, Cl:{perf.get('Closes',0)})")
                 except Exception as e_future: print_color(f"检索测试结果时出错: {e_future}", Fore.RED); err_idx = f"{current_batch_start_index + len(batch_results_temp)}?"; tb_str_future = traceback.format_exc(); batch_results_temp.append({"index":err_idx,"type":test_mode,"status":"FAIL_FUTURE_ERROR","errors":[f"Future Error: {e_future}\n{tb_str_future}"],"stderr":"","real_time_taken":-1})
        batch_end_time = time.time(); print(f"--- 批次完成于 {batch_end_time - batch_start_time:.2f} 秒 ---"); all_results.extend(batch_results_temp); tests_completed_count += num_tests_in_batch

    overall_end_time = time.time()
    print(f"\n所有 {total_tests_to_run} 个测试完成。总执行时间: {overall_end_time - overall_start_time:.2f} 秒。")

    total_passed_count = 0; total_failed_tests_summary = []
    all_results.sort(key=lambda x: x.get("index", float('inf')))
    for result in all_results:
        if result.get('status') == "PASS": total_passed_count += 1
        else: total_failed_tests_summary.append(result)
    print("\n" + "="*20 + f" 最终测试总结 (HW7 - 模式: {test_mode.capitalize()}) " + "="*20)
    print_color(f"总执行测试数: {len(all_results)}", Style.BRIGHT); print_color(f"通过: {total_passed_count}", Fore.GREEN)
    failed_count = len(total_failed_tests_summary); print_color(f"失败: {failed_count}", Fore.RED if failed_count > 0 else Fore.WHITE)
    if total_failed_tests_summary:
        print("\n--- 失败测试详情 ---")
        reason_map = { "FAIL_VALIDATE": "验证错误", "FAIL_TIMEOUT": "超时", "FAIL_RUNTIME": "运行时错误", "FAIL_JAVA_ERROR": "Java错误(非0退出)", "FAIL_STDERR_OUTPUT": "Stderr非空", "FAIL_GENERATE": "数据生成错误", "FAIL_SETUP": "设置错误", "FAIL_WRAPPER_ERROR": "包装器错误(见日志)", "FAIL_FUTURE_ERROR": "并行错误(见日志)", "FAIL_VALIDATE_RECHECK": "重新验证失败(见日志)", "FAIL_PERF_CALC_ERROR": "性能计算出错(见日志)", "FAIL_UNKNOWN": "未知" }
        for failure in total_failed_tests_summary:
             idx = failure.get("index", "?"); ftype = failure.get("type", "?"); code = failure.get("status", "FAIL_UNKNOWN"); reason_str = reason_map.get(code, code)
             print_color(f"  测试 {idx} ({ftype}): {reason_str}", Fore.RED); print(f"      输入:  {results_dir_path.name}{os.sep}failed_data_{idx}_{ftype}.txt"); print(f"      输出/日志: {results_dir_path.name}{os.sep}failed_stdout_{idx}_{ftype}.txt")
             errors = failure.get("errors", []); stderr_content = failure.get('stderr','')
             if code == "FAIL_TIMEOUT": print(f"      超时时间: {TIMEOUT_SECONDS_MUTUAL if ftype=='mutual' else TIMEOUT_SECONDS_PUBLIC}s")
             elif errors: print(f"      关键错误: {errors[0][:150]}...");
             if code == "FAIL_VALIDATE_RECHECK" and len(errors) > 1: print(f"      重验证首个错误: {errors[1][:150]}...")
             elif stderr_content.strip(): lines = [line for line in stderr_content.splitlines() if line.strip()];
             if lines: print(f"      Stderr 提示: ...{lines[-1][-100:]}")
    print("="* (50 + len(test_mode)))
    print(f"\n测试运行完成。请检查 '{RESULTS_DIR_NAME}' 目录获取失败详情。")