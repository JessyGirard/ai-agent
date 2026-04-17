import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import playground
from core import persistence as persistence_core


def _write_json(path, payload):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_soak(
    iterations=5000,
    verbose=True,
    progress_interval=500,
    result_path=None,
    checkpoint_path=None,
):
    original_memory_file = playground.MEMORY_FILE
    original_state_file = playground.STATE_FILE
    original_journal_file = playground.JOURNAL_FILE
    original_journal_archive_file = playground.JOURNAL_ARCHIVE_FILE
    original_ask_ai = playground.ask_ai
    original_max_entries = playground.JOURNAL_MAX_ACTIVE_ENTRIES

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        playground.MEMORY_FILE = temp_root / "extracted_memory.json"
        playground.STATE_FILE = temp_root / "current_state.json"
        playground.JOURNAL_FILE = temp_root / "project_journal.jsonl"
        playground.JOURNAL_ARCHIVE_FILE = temp_root / "project_journal_archive.jsonl"
        playground.JOURNAL_MAX_ACTIVE_ENTRIES = max(1000, min(iterations, 10000))

        try:
            playground.current_state.clear()
            playground.current_state.update(playground.DEFAULT_STATE.copy())
            playground.recent_answer_history.clear()
            persistence_core.consume_persistence_health_events()
            playground.MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            playground.MEMORY_FILE.write_text(
                json.dumps({"meta": {}, "memory_items": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            playground.ask_ai = lambda messages, system_prompt=None: (
                "Answer:\nStable response.\n\n"
                "Current state:\nFocus: ai-agent project\nStage: Phase 5 testing\nAction type: test\n\n"
                "Next step:\nRun one focused validation."
            )

            prompts = [
                "What should I do next?",
                "How do I prefer to learn?",
                "How is this system built?",
                "This failed for me.",
                "I am working on the memory retrieval path.",
                "Can you fetch a webpage with tools?",
            ]

            started = time.perf_counter()
            completed = 0
            interrupted = False
            try:
                for i in range(iterations):
                    _ = playground.handle_user_input(prompts[i % len(prompts)])
                    completed = i + 1
                    if progress_interval > 0 and completed % progress_interval == 0:
                        elapsed = time.perf_counter() - started
                        per_iter = elapsed / max(1, completed)
                        remaining = max(0, iterations - completed)
                        eta = per_iter * remaining
                        checkpoint = {
                            "iterations": iterations,
                            "completed_iterations": completed,
                            "elapsed_seconds": round(elapsed, 3),
                            "estimated_remaining_seconds": round(eta, 3),
                            "status": "running",
                        }
                        _write_json(checkpoint_path, checkpoint)
                        if verbose:
                            print(
                                f"SOAK_PROGRESS: {completed}/{iterations} "
                                f"(elapsed={elapsed:.1f}s, eta~{eta:.1f}s)"
                            )
            except KeyboardInterrupt:
                interrupted = True

            events = persistence_core.consume_persistence_health_events()
            rows = playground.load_project_journal()
            memory_payload = playground.load_memory_payload()
            memory_count = len(memory_payload.get("memory_items", []))
            elapsed = time.perf_counter() - started

            result = {
                "iterations": iterations,
                "completed_iterations": completed,
                "journal_rows": len(rows),
                "memory_items": memory_count,
                "health_event_count": len(events),
                "health_events": events,
                "elapsed_seconds": round(elapsed, 3),
                "interrupted": interrupted,
            }

            ok = (not interrupted) and len(events) == 0 and len(rows) > 0 and completed == iterations
            result["ok"] = ok
            result["status"] = "pass" if ok else ("interrupted" if interrupted else "fail")
            _write_json(checkpoint_path, result)
            _write_json(result_path, result)
            if verbose:
                print(json.dumps(result, indent=2, ensure_ascii=False))
                print("SOAK_STATUS: PASS" if ok else "SOAK_STATUS: FAIL")
            return result
        finally:
            playground.MEMORY_FILE = original_memory_file
            playground.STATE_FILE = original_state_file
            playground.JOURNAL_FILE = original_journal_file
            playground.JOURNAL_ARCHIVE_FILE = original_journal_archive_file
            playground.ask_ai = original_ask_ai
            playground.JOURNAL_MAX_ACTIVE_ENTRIES = original_max_entries


def run_soak_chunked(
    iterations,
    chunk_size,
    verbose=True,
    progress_interval=500,
    result_path=None,
    checkpoint_path=None,
    aggregate_path=None,
):
    remaining = max(1, iterations)
    chunk = max(1, chunk_size)
    total_completed = 0
    all_ok = True
    chunks = []
    chunk_index = 0
    started = time.perf_counter()

    base_result = Path(result_path) if result_path else None
    base_checkpoint = Path(checkpoint_path) if checkpoint_path else None

    while remaining > 0:
        chunk_index += 1
        current = min(chunk, remaining)
        chunk_result_path = None
        chunk_checkpoint_path = None
        if base_result:
            chunk_result_path = str(base_result.with_name(f"{base_result.stem}_chunk{chunk_index}{base_result.suffix}"))
        if base_checkpoint:
            chunk_checkpoint_path = str(
                base_checkpoint.with_name(f"{base_checkpoint.stem}_chunk{chunk_index}{base_checkpoint.suffix}")
            )

        if verbose:
            print(f"SOAK_CHUNK_START: chunk={chunk_index} iterations={current}")

        result = run_soak(
            iterations=current,
            verbose=verbose,
            progress_interval=progress_interval,
            result_path=chunk_result_path,
            checkpoint_path=chunk_checkpoint_path,
        )
        chunks.append(result)
        total_completed += int(result.get("completed_iterations", 0))
        remaining -= current
        all_ok = all_ok and bool(result.get("ok"))

        aggregate = {
            "mode": "chunked",
            "iterations": iterations,
            "chunk_size": chunk,
            "completed_iterations": total_completed,
            "chunks_completed": chunk_index,
            "all_ok": all_ok,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "status": "running" if remaining > 0 else ("pass" if all_ok else "fail"),
            "chunks": chunks,
        }
        _write_json(aggregate_path, aggregate)
        _write_json(checkpoint_path, aggregate)
        _write_json(result_path, aggregate)

        if not result.get("ok"):
            break

    final = {
        "mode": "chunked",
        "iterations": iterations,
        "chunk_size": chunk,
        "completed_iterations": total_completed,
        "chunks_completed": len(chunks),
        "all_ok": all_ok and total_completed == iterations,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "status": "pass" if (all_ok and total_completed == iterations) else "fail",
        "chunks": chunks,
    }
    _write_json(aggregate_path, final)
    _write_json(checkpoint_path, final)
    _write_json(result_path, final)
    if verbose:
        print(json.dumps(final, indent=2, ensure_ascii=False))
        print("SOAK_STATUS: PASS" if final["all_ok"] else "SOAK_STATUS: FAIL")
    return final


def main():
    parser = argparse.ArgumentParser(description="Run long soak test for runtime stability.")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--progress-interval", type=int, default=500)
    parser.add_argument("--result-path", type=str, default="")
    parser.add_argument("--checkpoint-path", type=str, default="")
    parser.add_argument("--aggregate-path", type=str, default="")
    parser.add_argument("--chunk-size", type=int, default=0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    iterations = max(1, args.iterations)
    if args.chunk_size and args.chunk_size > 0 and args.chunk_size < iterations:
        result = run_soak_chunked(
            iterations=iterations,
            chunk_size=args.chunk_size,
            verbose=not args.quiet,
            progress_interval=max(0, args.progress_interval),
            result_path=(args.result_path or None),
            checkpoint_path=(args.checkpoint_path or None),
            aggregate_path=(args.aggregate_path or None),
        )
        if not result.get("all_ok"):
            raise SystemExit(1)
    else:
        result = run_soak(
            iterations=iterations,
            verbose=not args.quiet,
            progress_interval=max(0, args.progress_interval),
            result_path=(args.result_path or None),
            checkpoint_path=(args.checkpoint_path or None),
        )
        if not result.get("ok"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
