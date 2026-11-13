#!/usr/bin/env python3
"""Convert one data file into an MDV project folder.

Run with MDV's Python (/app/python/.venv/bin/python). Usage:
    convert_file.py <source file> <new project folder>

Supported: .h5ad (AnnData), .h5mu (MuData), .vcf/.vcf.gz (variants), and
.csv/.tsv with optional .gz (tables).
"""

import gzip
import os
import shutil
import sys
import tempfile
import warnings


def kind_of(path):
    """Returns the converter for a file name, or None if unsupported. Shared with the sync."""
    name = path.lower()
    if name.endswith(".gz"):
        name = name[:-3]
    for ext, kind in ((".h5ad", "anndata"), (".h5mu", "mudata"), (".vcf", "vcf"),
                      (".csv", "table"), (".tsv", "table")):
        if name.endswith(ext):
            if kind in ("anndata", "mudata") and path.lower().endswith(".gz"):
                return None
            return kind
    return None


def stem_of(path):
    name = os.path.basename(path)
    if name.lower().endswith(".gz"):
        name = name[:-3]
    return os.path.splitext(name)[0]


def convert(src, dest):
    warnings.filterwarnings("ignore")
    kind = kind_of(src)
    if kind is None:
        raise ValueError(f"unsupported file type: {src}")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if kind == "anndata":
        import scanpy
        from mdvtools.conversions import convert_scanpy_to_mdv
        convert_scanpy_to_mdv(dest, scanpy.read_h5ad(src))
    elif kind == "mudata":
        import mudata
        from mdvtools.conversions import convert_mudata_to_mdv
        convert_mudata_to_mdv(dest, mudata.read(src))
    elif kind == "vcf":
        from mdvtools.conversions import convert_vcf_to_mdv
        if src.lower().endswith(".gz"):
            with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(dest))) as tmp:
                plain = os.path.join(tmp, stem_of(src) + ".vcf")
                with gzip.open(src, "rb") as fin, open(plain, "wb") as fout:
                    shutil.copyfileobj(fin, fout, 1 << 20)
                convert_vcf_to_mdv(dest, plain)
        else:
            convert_vcf_to_mdv(dest, src)
    else:
        import pandas
        from mdvtools.mdvproject import MDVProject
        lower = src.lower().removesuffix(".gz")
        sep = "," if lower.endswith(".csv") else "\t"
        df = pandas.read_csv(src, sep=sep)
        MDVProject(dest).add_datasource(stem_of(src), df)


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    convert(argv[1], argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
