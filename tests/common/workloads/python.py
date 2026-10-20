import hashlib
import os
import random
import sys
import tempfile
from pathlib import Path

kind = sys.argv[1]
os.environ.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MPLBACKEND="Agg")
random.seed(189771)


def files():
    with tempfile.TemporaryDirectory(prefix="dependency-workload-") as directory:
        data = random.Random(189771).randbytes(1024 * 1024)
        path = Path(directory) / "fixture.bin"
        path.write_bytes(data)
        assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()


if kind == "notebook":
    import nbformat
    from nbclient import NotebookClient

    source = """
import hashlib, random, tempfile
from pathlib import Path
values = [random.Random(i).random() for i in range(100000)]
assert 49000 < sum(values) < 51000
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'fixture.bin'
    data = random.Random(189771).randbytes(1024 * 1024)
    path.write_bytes(data)
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()
print('dependency-workload-ok')
"""
    cell = nbformat.v4.new_code_cell(source)
    notebook = nbformat.v4.new_notebook(cells=[cell])
    NotebookClient(notebook, timeout=120, startup_timeout=60, kernel_name="python3").execute()
    assert any("dependency-workload-ok" in output.get("text", "") for output in cell.outputs)
elif kind == "gpu":
    import torch

    assert torch.cuda.is_available() and torch.cuda.device_count() == 1
    torch.manual_seed(189771)
    a = torch.rand((1024, 1024), device="cuda")
    for _ in range(8):
        result = a @ a
    torch.cuda.synchronize()
    assert torch.isfinite(result).all()
elif kind == "nemo":
    import torch
    from nemo.collections.asr.modules import ConvASREncoder, ConvASRDecoder

    assert torch.cuda.is_available() and torch.cuda.device_count() == 1
    torch.manual_seed(189771)
    encoder = ConvASREncoder(jasper=[dict(filters=32, repeat=1, kernel=[3], stride=[1],
        dilation=[1], dropout=0.0, residual=False)], activation="relu", feat_in=16).cuda()
    decoder = ConvASRDecoder(feat_in=32, num_classes=4, vocabulary=["a", "b", "c", " "]).cuda()
    values = torch.rand((2, 16, 128), device="cuda", requires_grad=True)
    encoded, _ = encoder(audio_signal=values, length=torch.tensor([128, 128], device="cuda"))
    loss = -decoder(encoder_output=encoded).mean()
    loss.backward()
    torch.cuda.synchronize()
    assert torch.isfinite(loss) and torch.isfinite(values.grad).all()
elif kind == "files":
    files()
else:
    raise ValueError("unknown workload")
print("dependency-workload-ok")
