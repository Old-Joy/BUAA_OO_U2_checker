import subprocess
import time
import os
import sys
import random
import shutil
import concurrent.futures
import pathlib
from generate_data import generate_requests_phased
from validator import OutputValidator
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    USE_COLOR = True
except ImportError:
    print("Colorama not found, output will be monochrome.")
    print("Install using: pip install colorama")
    class DummyStyle:
        def __getattr__(self, name): return ""
    Fore = DummyStyle(); Style = DummyStyle()
    USE_COLOR = False


BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATAPUT_EXE = BASE_DIR / "datainput_student_win64.exe"
JAVA_COMMAND = "java"
JAR_FILE = BASE_DIR / "code.jar"
OFFICIAL_JAR_FILE = BASE_DIR / "elevator1.jar" # <--- !!! 务必修改 !!!
MAIN_CLASS_NAME = "MainClass"
STDIN_FILENAME = "stdin.txt"
TIMEOUT_SECONDS = 130
MAX_WORKERS = 10 # 每次并行运行 10 个
TEST_SUBDIR_PREFIX = "test_run_"
RESULTS_DIR_NAME = "test_results"


def print_color(text, color):
    if USE_COLOR: print(color + text + Style.RESET_ALL)
    else: print(text)


def run_single_test_parallel_subdir(test_index, num_requests, base_path, results_path):
    """在 base_path 下的独立子目录中运行单个测试。"""
    status_code = "UNKNOWN"
    performance_data = None
    validation_errors = []
    stdout_lines = []
    stderr_output = ""
    real_time_taken = 0
    java_exit_code = -1

    test_subdir_path = base_path / f"{TEST_SUBDIR_PREFIX}{test_index}"
    try:
        test_subdir_path.mkdir(exist_ok=True)
        print(f"[Test {test_index}] Using subdir: {test_subdir_path}")

        required_files = [DATAPUT_EXE, JAR_FILE, OFFICIAL_JAR_FILE]
        print(f"[Test {test_index}] Copying files to subdir...")
        for f in required_files:
            if f.exists(): shutil.copy2(f, test_subdir_path / f.name)
            else: raise FileNotFoundError(f"Required file not found: {f}")

        local_stdin_path = test_subdir_path / STDIN_FILENAME
        print(f"[Test {test_index}] Generating data ({num_requests} reqs) into {local_stdin_path}...")

        if not generate_requests_phased(num_requests=num_requests, filename=local_stdin_path):

            status_code = "FAIL_GENERATE"; raise RuntimeError("Data generation failed.")

        classpath_sep = ";" if os.name == 'nt' else ":"
        classpath = f'"{JAR_FILE.name}"{classpath_sep}"{OFFICIAL_JAR_FILE.name}"'
        cmd = f'.\\{DATAPUT_EXE.name} | {JAVA_COMMAND} -cp {classpath} {MAIN_CLASS_NAME}'

        print(f"[Test {test_index}] Executing command in {test_subdir_path}: {cmd}")
        start_time = time.time()
        process = None
        try:
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding='utf-8', errors='replace', cwd=test_subdir_path)
            stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
            end_time = time.time(); real_time_taken = end_time - start_time
            stdout_lines = stdout.splitlines() if stdout else []; stderr_output = stderr if stderr else ""
            java_exit_code = process.returncode
            print(f"[Test {test_index}] Execution finished in {real_time_taken:.2f}s (Java Exit: {java_exit_code}).")
            if java_exit_code != 0: status_code = "FAIL_JAVA_ERROR"
            else: status_code = "EXECUTION_COMPLETE"
        except subprocess.TimeoutExpired:
            end_time = time.time(); real_time_taken = end_time - start_time
            print_color(f"[Test {test_index}] Error: Process timed out after {TIMEOUT_SECONDS}s.", Fore.RED)
            status_code = "FAIL_TIMEOUT"
            if process: process.kill();
        except Exception as e_exec:
            end_time = time.time(); real_time_taken = end_time - start_time
            print_color(f"[Test {test_index}] Error during execution: {e_exec}", Fore.RED)
            if process: process.kill()
            status_code = "FAIL_RUNTIME"; stderr_output += f"\n--- Python Execution Error ---\n{e_exec}"

        print(f"[Test {test_index}] Validating output...")
        validator = OutputValidator(local_stdin_path)
        validation_success = validator.validate_output(stdout_lines)
        validation_errors = validator.errors

        final_status = "UNKNOWN"
        if validation_success and status_code == "EXECUTION_COMPLETE":
            final_status = "PASS"
            performance_data = validator.calculate_performance(real_time_taken)
        else:
            if status_code.startswith("FAIL"): final_status = status_code
            elif not validation_success: final_status = "FAIL_VALIDATE"
            else: final_status = "FAIL_UNKNOWN"

            failed_data_filename = results_path / f"failed_data_{test_index}.txt"
            failed_stdout_filename = results_path / f"failed_stdout_{test_index}.txt"
            print_color(f"[Test {test_index}] Failed! Reason: {final_status}", Fore.RED)
            print(f"[Test {test_index}] Saving failed data to {failed_data_filename}")
            try: shutil.copyfile(local_stdin_path, failed_data_filename)
            except Exception as e_copy: print_color(f"  [T{test_index}] Error copying input: {e_copy}", Fore.YELLOW)
            print(f"[Test {test_index}] Saving failed output/stderr to {failed_stdout_filename}")
            try:
                with open(failed_stdout_filename, "w", encoding='utf-8', errors='replace') as f:
                     f.write("--- STDOUT ---\n"); f.write("\n".join(stdout_lines))
                     f.write("\n\n--- STDERR ---\n"); f.write(stderr_output)
                     f.write(f"\n\n--- Execution Status Code: {status_code} ---\n")
                     f.write(f"--- Java Exit Code: {java_exit_code} ---\n")
                     if validation_errors:
                         f.write("\n--- Validation Errors ---\n")
                         for v_err in validation_errors: f.write(f"{v_err}\n")
            except IOError as e_write: print_color(f"  [T{test_index}] Error writing output: {e_write}", Fore.YELLOW)

    except FileNotFoundError as e_fnf:
         print_color(f"[Test {test_index}] Error: Required file not found during setup: {e_fnf}", Fore.RED)
         final_status = "FAIL_SETUP"; validation_errors.append(f"Setup Error: {e_fnf}")
    except Exception as e_outer:
         print_color(f"[Test {test_index}] Error in test wrapper: {e_outer}", Fore.RED)
         final_status = "FAIL_WRAPPER_ERROR"; validation_errors.append(f"Wrapper Error: {e_outer}")
         import traceback; traceback.print_exc()
    finally:
        try:
            if test_subdir_path.exists():
                print(f"[Test {test_index}] Cleaning up subdir: {test_subdir_path}")
                shutil.rmtree(test_subdir_path)
        except Exception as e_clean:
            print_color(f"[Test {test_index}] Warning: Failed to clean up subdir {test_subdir_path}: {e_clean}", Fore.YELLOW)

    return {"index": test_index, "status": final_status, "performance": performance_data,
            "errors": validation_errors, "stderr": stderr_output, "real_time_taken": real_time_taken}



if __name__ == "__main__":
    while True:
        try:
            total_test_cases_input = input("请输入要运行的总测试点数量 (必须是 10 的倍数): ")
            total_test_cases = int(total_test_cases_input)
            if total_test_cases > 0 and total_test_cases % 10 == 0: break
            else: print_color("输入无效，请输入一个大于 0 且是 10 的倍数的整数。", Fore.RED)
        except ValueError: print_color("输入无效，请输入一个整数。", Fore.RED)

    total_passed_count = 0; total_failed_tests_summary = []; all_results = []
    tests_completed_count = 0
    results_dir = BASE_DIR / RESULTS_DIR_NAME; results_dir.mkdir(exist_ok=True)

    print("Cleaning up potential leftover test subdirectories...")
    for item in BASE_DIR.glob(f"{TEST_SUBDIR_PREFIX}*"):
        if item.is_dir():
            try: shutil.rmtree(item); print(f"  Removed old subdir: {item.name}")
            except Exception as e_clean_old: print_color(f"  Warning: Could not remove old subdir {item.name}: {e_clean_old}", Fore.YELLOW)

    if not DATAPUT_EXE.exists(): print_color(f"Error: Datainput not found: {DATAPUT_EXE}", Fore.RED); sys.exit(1)
    if not JAR_FILE.exists(): print_color(f"Error: JAR file not found: {JAR_FILE}", Fore.RED); sys.exit(1)
    if not OFFICIAL_JAR_FILE.exists(): print_color(f"Error: Official library not found: {OFFICIAL_JAR_FILE}", Fore.RED); sys.exit(1)

    overall_start_time = time.time()
    print(f"\nStarting total {total_test_cases} tests in batches of {MAX_WORKERS}...")

    while tests_completed_count < total_test_cases:
        current_batch_start_index = tests_completed_count + 1
        num_tests_in_batch = min(MAX_WORKERS, total_test_cases - tests_completed_count)
        current_batch_end_index = current_batch_start_index + num_tests_in_batch - 1

        print(f"\n--- Running Batch: Tests {current_batch_start_index} to {current_batch_end_index} ---")
        batch_start_time = time.time()
        futures = []; batch_results_temp = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i in range(num_tests_in_batch):
                test_case_index = current_batch_start_index + i
                req_count = random.randint(80, 100) # <--- 请求数量范围调整到 80-100
                future = executor.submit(run_single_test_parallel_subdir, test_case_index, req_count, BASE_DIR, results_dir)
                futures.append(future)

            print(f"Waiting for batch (Tests {current_batch_start_index}-{current_batch_end_index}) to complete...")
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result(); batch_results_temp.append(result)
                    status_color = Fore.GREEN if result['status'] == 'PASS' else Fore.RED
                    print_color(f"  Test {result['index']} finished with status: {result['status']}", status_color)
                    if result['status'] == 'PASS':
                        perf = result.get('performance')
                        if perf:
                            print(f"    Performance Metrics (Test {result['index']}):")
                            real_time = result.get('real_time_taken', -1.0); real_time_str = f"(Real time: {real_time:.3f}s)" if real_time >= 0 else ""
                            print(f"      T_run (Real/Output Max): {perf['T_run']:.3f}s {real_time_str}")
                            wt_str = f"{perf['WT']:.3f}" if perf['WT'] != float('inf') else "Inf (Error/No valid passengers)"
                            print(f"      WT (Avg Weighted Time): {wt_str}")
                            print(f"      W (Power): {perf['W']:.2f} (Arrive:{perf['Arrives']}, Open:{perf['Opens']}, Close:{perf['Closes']})")
                except Exception as e_future:
                    print_color(f"Error retrieving result for one test in batch: {e_future}", Fore.RED)
                    batch_results_temp.append({"index": f"{current_batch_start_index+len(batch_results_temp)}?", "status": "FAIL_FUTURE_ERROR", "errors": [f"Future Error: {e_future}"], "stderr":""})

        batch_end_time = time.time()
        print(f"--- Batch Finished in {batch_end_time - batch_start_time:.2f} seconds ---")
        all_results.extend(batch_results_temp); tests_completed_count += num_tests_in_batch

    overall_end_time = time.time()
    print(f"\nAll {total_test_cases} tests finished. Total execution time: {overall_end_time - overall_start_time:.2f} seconds.")


    all_results.sort(key=lambda x: x.get("index", float('inf')) if isinstance(x.get("index"), int) else float('inf'))
    for result in all_results:
        if result.get('status') == "PASS": total_passed_count += 1
        else: total_failed_tests_summary.append({ "index": result.get("index", "?"), "reason_code": result.get("status", "FAIL_UNKNOWN"), "validation_errors": result.get("errors", []), "stderr": result.get("stderr", "") })
    print("\n" + "="*20 + " Final Test Summary " + "="*20)
    print_color(f"Total Tests Attempted: {total_test_cases}", Style.BRIGHT)
    print_color(f"Total Tests Completed: {len(all_results)}", Style.BRIGHT)
    print_color(f"Passed: {total_passed_count}", Fore.GREEN)
    failed_count = len(total_failed_tests_summary)
    print_color(f"Failed: {failed_count}", Fore.RED if failed_count > 0 else Fore.WHITE)
    if total_failed_tests_summary:
        print("\n--- Failed Test Details ---")
        for failure in total_failed_tests_summary:
            reason_map = { "FAIL_VALIDATE": "Validation Error(s)", "FAIL_TIMEOUT": "Execution Timeout", "FAIL_RUNTIME": "Runtime Error during execution", "FAIL_JAVA_ERROR": "Java Error", "FAIL_GENERATE": "Data Generation Error", "FAIL_SETUP": "Setup Error (Files not found)", "FAIL_WRAPPER_ERROR": "Test Wrapper Error", "FAIL_FUTURE_ERROR": "Parallel Execution Error", "FAIL_UNKNOWN": "Unknown Failure" }
            reason_str = reason_map.get(failure['reason_code'], failure['reason_code'])
            print_color(f"  Test Case {failure['index']}: {reason_str}", Fore.RED)
            print(f"      Input:  {RESULTS_DIR_NAME}\\failed_data_{failure['index']}.txt")
            print(f"      Output: {RESULTS_DIR_NAME}\\failed_stdout_{failure['index']}.txt")
    print("="*56)