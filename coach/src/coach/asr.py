"""Vietnamese speech recognition.

CPU uses faster-whisper. GPU uses MLX on the Apple GPU. CTranslate2 on this
Mac has no CUDA and no Metal device, so the PhoWhisper checkpoint is converted
once into MLX weights and then run with mlx.core's default GPU.
"""

from __future__ import annotations

import json
from pathlib import Path

from coach.settings import ROOT
from coach.voice_stack import WHISPER_GPU_MODEL

_GPU_DEVICES = {"gpu", "metal", "mlx"}


def transcribe_pcm(
    samples,
    *,
    model: str,
    language: str,
    device: str = "cpu",
    compute_type: str = "int8",
) -> tuple[str, str]:
    """Transcribe 16 kHz float32 audio. Returns text and the backend name."""

    if device.strip().lower() in _GPU_DEVICES:
        return _transcribe_mlx(samples, model=model, language=language), "mlx-gpu"
    return _transcribe_cpu(samples, model=model, language=language, compute_type=compute_type), "faster-whisper-cpu"


def gpu_repo(model: str) -> str:
    """CTranslate2 checkpoints cannot run on MLX. Those names use the GPU PhoWhisper."""

    name = model.strip()
    if not name or name.endswith("-ct2"):
        return WHISPER_GPU_MODEL
    return name


def mlx_weights_dir(repo: str = WHISPER_GPU_MODEL) -> Path:
    slug = gpu_repo(repo).rstrip("/").split("/")[-1]
    return ROOT / ".cache" / "phowhisper-mlx" / slug


def ensure_mlx_weights(repo: str = WHISPER_GPU_MODEL) -> Path:
    dest = mlx_weights_dir(repo)
    weights = dest / "weights.safetensors"
    config = dest / "config.json"
    if weights.is_file() and config.is_file():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    _convert_hf_whisper(gpu_repo(repo), dest)
    return dest


def _transcribe_mlx(samples, *, model: str, language: str) -> str:
    import mlx.core as mx
    import mlx_whisper

    if mx.default_device().type != mx.DeviceType.gpu:
        raise RuntimeError(f"MLX is not on the GPU: {mx.default_device()}")
    weights = ensure_mlx_weights(model)
    result = mlx_whisper.transcribe(
        samples,
        path_or_hf_repo=str(weights),
        language=language,
        verbose=False,
        condition_on_previous_text=False,
    )
    mx.synchronize()
    if mx.get_active_memory() <= 0:
        raise RuntimeError("MLX transcribed without allocating GPU memory")
    return str(result.get("text", "")).strip()


def _transcribe_cpu(samples, *, model: str, language: str, compute_type: str) -> str:
    from faster_whisper import WhisperModel

    whisper = WhisperModel(model, device="cpu", compute_type=compute_type)
    segments, _info = whisper.transcribe(samples, language=language)
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def _convert_hf_whisper(repo: str, dest: Path) -> None:
    import mlx.core as mx
    from huggingface_hub import snapshot_download
    from mlx.utils import tree_flatten
    from mlx_whisper.whisper import ModelDimensions, Whisper

    source = Path(
        snapshot_download(
            repo_id=repo,
            allow_patterns=["config.json", "model.safetensors", "pytorch_model.bin"],
        )
    )
    with open(source / "config.json", encoding="utf-8") as handle:
        hf_config = json.load(handle)
    weight_file = source / "model.safetensors"
    if weight_file.is_file():
        raw = mx.load(str(weight_file))
    else:
        import torch

        raw = {
            key: mx.array(value.detach())
            for key, value in torch.load(source / "pytorch_model.bin", map_location="cpu").items()
        }
    mapped, dims = _hf_to_mlx(raw, hf_config)
    model = Whisper(ModelDimensions(**dims), mx.float16)
    model.load_weights(list(mapped.items()), strict=False)
    flat = dict(tree_flatten(model.parameters()))
    if len(flat) < 100:
        raise RuntimeError(f"PhoWhisper conversion produced only {len(flat)} tensors")
    mx.save_safetensors(str(dest / "weights.safetensors"), flat)
    payload = dict(dims)
    payload["model_type"] = "whisper"
    (dest / "config.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _hf_to_mlx(weights: dict, config: dict) -> tuple[dict, dict]:
    import mlx.core as mx

    dims = {
        "n_mels": int(config["num_mel_bins"]),
        "n_audio_ctx": int(config["max_source_positions"]),
        "n_audio_state": int(config["d_model"]),
        "n_audio_head": int(config["encoder_attention_heads"]),
        "n_audio_layer": int(config["encoder_layers"]),
        "n_vocab": int(config["vocab_size"]),
        "n_text_ctx": int(config["max_target_positions"]),
        "n_text_state": int(config["d_model"]),
        "n_text_head": int(config["decoder_attention_heads"]),
        "n_text_layer": int(config["decoder_layers"]),
    }

    def remap(key: str) -> str:
        key = key.replace("model.", "")
        key = key.replace(".layers", ".blocks")
        key = key.replace(".self_attn", ".attn")
        key = key.replace(".attn_layer_norm", ".attn_ln")
        key = key.replace(".encoder_attn.", ".cross_attn.")
        key = key.replace(".encoder_attn_layer_norm", ".cross_attn_ln")
        key = key.replace(".final_layer_norm", ".mlp_ln")
        key = key.replace(".q_proj", ".query")
        key = key.replace(".k_proj", ".key")
        key = key.replace(".v_proj", ".value")
        key = key.replace(".out_proj", ".out")
        key = key.replace(".fc1", ".mlp1")
        key = key.replace(".fc2", ".mlp2")
        key = key.replace("embed_positions.weight", "positional_embedding")
        key = key.replace("decoder.embed_tokens", "decoder.token_embedding")
        key = key.replace("encoder.layer_norm", "encoder.ln_post")
        key = key.replace("decoder.layer_norm", "decoder.ln")
        key = key.replace("mlp.0", "mlp1")
        key = key.replace("mlp.2", "mlp2")
        return key

    mapped: dict = {}
    for key, value in weights.items():
        if key.endswith("proj_out.weight"):
            continue
        name = remap(key)
        array = value.astype(mx.float16)
        if "conv" in name and array.ndim == 3:
            array = array.swapaxes(1, 2)
        mapped[name] = array
    mapped.pop("encoder.positional_embedding", None)
    return mapped, dims
