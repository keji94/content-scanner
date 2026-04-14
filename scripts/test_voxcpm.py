#!/usr/bin/env python3
"""VoxCPM 2 inference test script.

Verifies model loading and basic TTS generation on available hardware.
"""

import argparse
import json
import sys
import time
import os


def main():
    parser = argparse.ArgumentParser(description="Test VoxCPM 2 inference")
    parser.add_argument("--device", default=None, help="Force device (mps/cuda/cpu)")
    parser.add_argument("--output-dir", default="/tmp/voxcpm-test", help="Output directory")
    args = parser.parse_args()

    import torch
    print(f"PyTorch: {torch.__version__}", file=sys.stderr)
    print(f"MPS available: {torch.backends.mps.is_available()}", file=sys.stderr)
    print(f"CUDA available: {torch.cuda.is_available()}", file=sys.stderr)

    # Determine device
    if args.device:
        device = args.device
    elif torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    print(f"Using device: {device}", file=sys.stderr)

    os.makedirs(args.output_dir, exist_ok=True)

    results = {"device": device, "tests": []}

    # Load model
    print("Loading VoxCPM 2 model...", file=sys.stderr)
    t0 = time.time()
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    load_time = time.time() - t0
    print(f"Model loaded in {load_time:.1f}s", file=sys.stderr)

    import soundfile as sf

    # Test 1: Chinese text
    test_text_zh = "你好，欢迎使用语音合成测试。这是一个开源的文本转语音模型。"
    print(f"\nTest 1 (Chinese): {test_text_zh}", file=sys.stderr)
    t0 = time.time()
    wav = model.generate(text=test_text_zh, cfg_value=2.0, inference_timesteps=10)
    gen_time = time.time() - t0
    out_path = os.path.join(args.output_dir, "test_zh.wav")
    sf.write(out_path, wav, model.tts_model.sample_rate)
    duration = len(wav) / model.tts_model.sample_rate
    results["tests"].append({
        "name": "chinese_basic",
        "text": test_text_zh,
        "output": out_path,
        "duration_seconds": round(duration, 2),
        "generate_time": round(gen_time, 2),
        "rtf": round(gen_time / duration, 3) if duration > 0 else 0,
        "sample_rate": model.tts_model.sample_rate,
    })
    print(f"  Generated {duration:.2f}s audio in {gen_time:.2f}s (RTF={gen_time/duration:.3f})", file=sys.stderr)

    # Test 2: English text
    test_text_en = "Hello, welcome to the VoxCPM text to speech demonstration."
    print(f"\nTest 2 (English): {test_text_en}", file=sys.stderr)
    t0 = time.time()
    wav = model.generate(text=test_text_en, cfg_value=2.0, inference_timesteps=10)
    gen_time = time.time() - t0
    out_path = os.path.join(args.output_dir, "test_en.wav")
    sf.write(out_path, wav, model.tts_model.sample_rate)
    duration = len(wav) / model.tts_model.sample_rate
    results["tests"].append({
        "name": "english_basic",
        "text": test_text_en,
        "output": out_path,
        "duration_seconds": round(duration, 2),
        "generate_time": round(gen_time, 2),
        "rtf": round(gen_time / duration, 3) if duration > 0 else 0,
        "sample_rate": model.tts_model.sample_rate,
    })
    print(f"  Generated {duration:.2f}s audio in {gen_time:.2f}s (RTF={gen_time/duration:.3f})", file=sys.stderr)

    # Test 3: Voice design
    test_text_vd = "(年轻女性，温柔甜美的声音)你好，很高兴认识你。今天天气真好，我们一起去公园散步吧。"
    print(f"\nTest 3 (Voice Design): {test_text_vd}", file=sys.stderr)
    t0 = time.time()
    wav = model.generate(text=test_text_vd, cfg_value=2.0, inference_timesteps=10)
    gen_time = time.time() - t0
    out_path = os.path.join(args.output_dir, "test_voice_design.wav")
    sf.write(out_path, wav, model.tts_model.sample_rate)
    duration = len(wav) / model.tts_model.sample_rate
    results["tests"].append({
        "name": "voice_design",
        "text": test_text_vd,
        "output": out_path,
        "duration_seconds": round(duration, 2),
        "generate_time": round(gen_time, 2),
        "rtf": round(gen_time / duration, 3) if duration > 0 else 0,
    })
    print(f"  Generated {duration:.2f}s audio in {gen_time:.2f}s (RTF={gen_time/duration:.3f})", file=sys.stderr)

    # Summary
    results["status"] = "success"
    results["model_load_time"] = round(load_time, 1)
    print(f"\nAll tests passed. Outputs in {args.output_dir}/", file=sys.stderr)
    json.dump(results, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
