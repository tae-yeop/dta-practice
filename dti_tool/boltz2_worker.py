"""Run only inside the isolated Boltz environment; never acquire data here."""

import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import socket
import sys
import urllib.request


def deny_network(*args, **kwargs):
    raise RuntimeError("Network access is disabled during Boltz-2 prediction. Prepare all assets explicitly.")


def main():
    import torch
    import boltz.main as upstream
    from boltz.data import const
    from boltz.data.parse import yaml as input_parser
    from boltz.model.models import boltz2
    if version("boltz") != "2.2.1":
        raise RuntimeError("This worker requires boltz==2.2.1")
    runtime = {"python": platform.python_version(), "boltz": version("boltz"), "torch": torch.__version__,
               "rdkit": version("rdkit"), "cuda_available": torch.cuda.is_available(),
               "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
               "code_sha256": {"main.py": hashlib.sha256(Path(upstream.__file__).read_bytes()).hexdigest(),
                               "parse/yaml.py": hashlib.sha256(Path(input_parser.__file__).read_bytes()).hexdigest(),
                               "models/boltz2.py": hashlib.sha256(Path(boltz2.__file__).read_bytes()).hexdigest()}}
    if sys.argv[1:] == ["--probe"]:
        print(json.dumps(runtime))
        return
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    urllib.request.urlopen = deny_network
    urllib.request.urlretrieve = deny_network

    def check_prepared(cache):
        required = [cache / name for name in ("boltz2_conf.ckpt", "boltz2_aff.ckpt", "mols.tar")]
        required += [cache / "mols" / (name + ".pkl") for name in const.canonical_tokens]
        if not all(path.is_file() for path in required):
            raise RuntimeError("Boltz-2 assets incomplete; runtime downloads are disabled.")

    upstream.download_boltz2 = check_prepared
    if request["device"] == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Requested CUDA is unavailable")
    args = ["predict", request["input"], "--out_dir", request["output"], "--cache", request["cache"],
            "--model", "boltz2", "--accelerator", "gpu" if request["device"] == "cuda" else "cpu",
            "--devices", "1", "--num_workers", "0", "--preprocessing-threads", "1", "--no_kernels"]
    for key in ("recycling_steps", "sampling_steps", "diffusion_samples", "sampling_steps_affinity",
                "diffusion_samples_affinity", "max_parallel_samples", "seed"):
        args += ["--" + key, str(request["parameters"][key])]
    print(json.dumps({"runtime": runtime, "offline": True, "parameters": request["parameters"]}), flush=True)
    upstream.cli(args, standalone_mode=False)


if __name__ == "__main__":
    main()
