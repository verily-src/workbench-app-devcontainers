#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail
command -v pbrun >/dev/null
command -v bwa >/dev/null
command -v samtools >/dev/null
fixture=$(mktemp -d)
trap 'rm -rf "${fixture}"' EXIT
python3 - "${fixture}" <<'PY'
import random, sys
from pathlib import Path
root = Path(sys.argv[1])
rng = random.Random(189771)
reference = ''.join(rng.choices('ACGT', k=1000000))
(root / 'ref.fa').write_text('>chrFixture\n' + '\n'.join(reference[i:i+80] for i in range(0,len(reference),80)) + '\n')
complement = str.maketrans('ACGT','TGCA')
with (root / 'reads_1.fq').open('w') as first, (root / 'reads_2.fq').open('w') as second:
    for i in range(1000):
        start = rng.randrange(0,len(reference)-400)
        a = reference[start:start+150]
        b = reference[start+250:start+400].translate(complement)[::-1]
        first.write(f'@read{i}/1\n{a}\n+\n' + 'I'*150 + '\n')
        second.write(f'@read{i}/2\n{b}\n+\n' + 'I'*150 + '\n')
PY
bwa index "${fixture}/ref.fa"
samtools faidx "${fixture}/ref.fa"
pbrun fq2bam --ref "${fixture}/ref.fa" --in-fq "${fixture}/reads_1.fq" "${fixture}/reads_2.fq" \
    --out-bam "${fixture}/result.bam" --num-gpus 1 --low-memory
[[ $(samtools view -c "${fixture}/result.bam") -ge 1000 ]]
echo dependency-workload-ok
