"""
Hypertrophic cardiomyopathy: sarcomere genes (MYH7, MYBPC3, TNNT2, TNNI3, TPM1, ACTC1).

The story: MYBPC3 loss of function, the commonest cause of HCM -- a nonsense variant, a
frameshift and a splice acceptor variant -- is enriched in the matched cohort alongside classic
missense variants: MYH7 p.Arg403Gln, MYBPC3's founder p.Arg502Trp (seen hundreds of times in
gnomAD's Europeans), and MYBPC3 p.Glu258Lys, a missense change at the end of an exon whose real
effect is on splicing. Against them: a common MYBPC3 synonymous variant and a benign MYBPC3
missense variant at background, and TNNT2's legacy "R278C", once reported as pathogenic and now
likely benign, in nobody matched. A MYBPC3 VUS turns up in nobody matched too, and a second VUS
isn't in All of Us at all.

Variants checked against ClinVar and Ensembl VEP (MANE Select), 2026-09-29. SpliceAI, REVEL and
LOFTEE calls come from VEP's plugins; gnomAD counts are gnomAD v4 genomes', from its API. TNNT2's
p.Arg102Gln and p.Arg288Cys are the legacy "R92Q" and "R278C", renumbered on the MANE transcript.
"""

from .common import ClinVar, Condition, Matched, UseCase, Variant

CASE = UseCase(
    key="hypertrophic_cardiomyopathy",
    title="Hypertrophic cardiomyopathy",
    description="Sarcomere genes",
    condition=Condition(concept_id=9000040, name="Hypertrophic cardiomyopathy", est_count=212, participants=214, synonyms=('hcm', 'hocm', 'hypertrophic obstructive cardiomyopathy')),
    ancestry={"EUR": 118, "AFR": 38, "AMR": 30, "OTH": 16, "EAS": 6, "SAS": 4, "MID": 2},
    age={"18–29": 12, "30–39": 24, "40–49": 38, "50–59": 52, "60–69": 54, "70+": 34},
    variants=(
        Variant(
            vid="14-23429278-C-T", gene="MYH7", gene_id="ENSG00000092054",
            transcript="ENST00000355349", mane="NM_000257.4", hgvsc="c.1208G>A", hgvsp='p.Arg403Gln',
            consequence=('missense_variant',), exon="13/40", rsid='rs121913624',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="reviewed by expert panel", last_evaluated="2016-12-15",
                rcvs=('RCV000015143', 'RCV000035708', 'RCV000158788', 'RCV000199447', 'RCV001798006', 'RCV002345242'),
                conditions=('Hypertrophic cardiomyopathy',),
            ),
            aou={"eur": 3},
            gnomad=None,
            revel=0.886,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0.02, "DS_DL": 0, "DP_AG": -2, "DP_AL": 30, "DP_DG": -1, "DP_DL": -18},
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="11-47342698-G-A", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.1504C>T", hgvsp='p.Arg502Trp',
            consequence=('missense_variant',), exon="17/35", rsid='rs375882485',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-03-04",
                rcvs=('RCV000035406', 'RCV000203913', 'RCV000223898', 'RCV000252398', 'RCV000584810', 'RCV000677196'),
                conditions=('Hypertrophic cardiomyopathy 4', 'MYBPC3-related cardiomyopathies'),
            ),
            aou={"eur": 0.00018, "afr": 6.3e-05, "sas": 2.2e-05, "mid": 0.00017, "oth": 0.0001},
            gnomad={"oth": (0, 2090), "amr": (1, 15278), "fin": (0, 10618), "eas": (0, 5194), "sas": (0, 4836), "asj": (0, 3472), "afr": (1, 41450), "nfe": (11, 68032)},
            revel=0.64,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 39, "DP_AL": 46, "DP_DG": 2, "DP_DL": 5},
            matched=Matched(carriers_ac=6),
        ),
        # The last base of exon 6: missense, but it's the splicing it breaks that's pathogenic.
        Variant(
            vid="11-47348424-C-T", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.772G>A", hgvsp='p.Glu258Lys',
            consequence=('missense_variant', 'splice_region_variant'), exon="6/35", rsid='rs397516074',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-02",
                rcvs=('RCV000035668', 'RCV000161125', 'RCV000205517', 'RCV000158310', 'RCV000247227', 'RCV000763244'),
                conditions=('Hypertrophic cardiomyopathy 4', 'Left ventricular noncompaction 10'),
            ),
            aou={"eur": 6, "amr": 1},
            gnomad={"oth": (0, 2090), "amr": (0, 15276), "fin": (0, 10618), "eas": (0, 5184), "sas": (0, 4834), "asj": (0, 3472), "afr": (2, 41426), "nfe": (3, 68034)},
            revel=0.616,
            splice_ai={"DS_AG": 0.01, "DS_AL": 0, "DS_DG": 0.01, "DS_DL": 0.17, "DP_AG": -2, "DP_AL": -1, "DP_DG": -14, "DP_DL": 0},
            matched=Matched(carriers_ac=3),
        ),
        Variant(
            vid="1-201365297-C-T", gene="TNNT2", gene_id="ENSG00000118194",
            transcript="ENST00000656932", mane="NM_001276345.2", hgvsc="c.305G>A", hgvsp='p.Arg102Gln',
            consequence=('missense_variant',), exon="10/17", rsid='rs121964856',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-01-21",
                rcvs=('RCV000013220', 'RCV000211865', 'RCV000159281', 'RCV000621709', 'RCV000627784', 'RCV003450626'),
                conditions=('Hypertrophic cardiomyopathy 2', 'Dilated cardiomyopathy 1D', 'Cardiomyopathy, familial restrictive, 3'),
            ),
            aou={"eur": 3, "afr": 1},
            gnomad={"oth": (0, 2094), "amr": (0, 15284), "fin": (0, 10616), "eas": (0, 5194), "sas": (0, 4832), "asj": (0, 3472), "afr": (0, 41442), "nfe": (1, 68036)},
            splice_ai={"DS_AG": 0.01, "DS_AL": 0.05, "DS_DG": 0, "DS_DL": 0, "DP_AG": -2, "DP_AL": 38, "DP_DG": -2, "DP_DL": -34},
            matched=Matched(carriers_ac=1),
        ),
        Variant(
            vid="19-55154146-G-C", gene="TNNI3", gene_id="ENSG00000129991",
            transcript="ENST00000344887", mane="NM_000363.5", hgvsc="c.433C>G", hgvsp='p.Arg145Gly',
            consequence=('missense_variant',), exon="7/8", rsid='rs104894724',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2024-01-04",
                rcvs=('RCV000013231', 'RCV000251781', 'RCV000441050', 'RCV000557688', 'RCV001798003'),
                conditions=('Hypertrophic cardiomyopathy 7', 'Cardiomyopathy'),
            ),
            aou={"eur": 1, "oth": 1},
            gnomad=None,
            revel=0.832,
            splice_ai={"DS_AG": 0, "DS_AL": 0.01, "DS_DG": 0, "DS_DL": 0, "DP_AG": -36, "DP_AL": 23, "DP_DG": 24, "DP_DL": -5},
            matched=Matched(carriers_ac=1),
        ),
        Variant(
            vid="11-47351379-G-A", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.152C>T", hgvsp='p.Ala51Val',
            consequence=('missense_variant',), exon="2/35", rsid='rs746738538',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, single submitter", last_evaluated="2024-09-10",
                rcvs=('RCV006829806',),
                conditions=(),
            ),
            aou={"afr": 12, "eur": 7, "amr": 2},
            gnomad=None,
            revel=0.152,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -4, "DP_AL": 22, "DP_DG": 35, "DP_DL": -9},
            matched=Matched(carriers_ac=0),
        ),
        Variant(
            vid="14-23426833-C-T", gene="MYH7", gene_id="ENSG00000092054",
            transcript="ENST00000355349", mane="NM_000257.4", hgvsc="c.1988G>A", hgvsp='p.Arg663His',
            consequence=('missense_variant',), exon="18/40", rsid='rs371898076',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="reviewed by expert panel", last_evaluated="2016-12-15",
                rcvs=('RCV000035758', 'RCV000162333', 'RCV000158822', 'RCV000168409', 'RCV000253409', 'RCV000477919'),
                conditions=('Hypertrophic cardiomyopathy',),
            ),
            aou={"eur": 3, "afr": 1},
            gnomad={"oth": (0, 2078), "amr": (1, 15240), "fin": (0, 10534), "eas": (0, 5146), "sas": (0, 4808), "asj": (0, 3470), "afr": (0, 41272), "nfe": (5, 67984)},
            revel=0.742,
            splice_ai={"DS_AG": 0, "DS_AL": 0.07, "DS_DG": 0, "DS_DL": 0.02, "DP_AG": -2, "DP_AL": 31, "DP_DG": 31, "DP_DL": -19},
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="15-63060899-G-A", gene="TPM1", gene_id="ENSG00000140416",
            transcript="ENST00000403994", mane="NM_001018005.2", hgvsc="c.523G>A", hgvsp='p.Asp175Asn',
            consequence=('missense_variant',), exon="5/10", rsid='rs104894503',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-01-31",
                rcvs=('RCV000013272', 'RCV000159366', 'RCV000474684', 'RCV000622165', 'RCV001197088', 'RCV001170568'),
                conditions=('Hypertrophic cardiomyopathy', 'Primary dilated cardiomyopathy'),
            ),
            aou={"eur": 2},
            gnomad={"oth": (0, 2092), "amr": (0, 15280), "fin": (2, 10620), "eas": (0, 5202), "sas": (0, 4826), "asj": (1, 3472), "afr": (0, 41434), "nfe": (1, 68044)},
            revel=0.785,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 16, "DP_AL": -30, "DP_DG": -24, "DP_DL": 40},
            matched=Matched(carriers_ac=1),
        ),
        Variant(
            vid="15-34793398-C-T", gene="ACTC1", gene_id="ENSG00000159251",
            transcript="ENST00000290378", mane="NM_005159.5", hgvsc="c.301G>A", hgvsp='p.Glu101Lys',
            consequence=('missense_variant',), exon="3/7", rsid='rs193922680',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="reviewed by expert panel", last_evaluated="2025-11-14",
                rcvs=('RCV000019996', 'RCV000019997', 'RCV000029295', 'RCV000157780', 'RCV000684792', 'RCV000769471'),
                conditions=('Hypertrophic cardiomyopathy',),
            ),
            aou={"eur": 1, "amr": 1},
            gnomad={"oth": (0, 2084), "amr": (0, 15274), "fin": (0, 10606), "eas": (0, 5184), "sas": (0, 4824), "asj": (0, 3470), "afr": (0, 41426), "nfe": (1, 68002)},
            revel=0.873,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -3, "DP_AL": -45, "DP_DG": -3, "DP_DL": 12},
            matched=Matched(carriers_ac=1),
        ),
        Variant(
            vid="1-201359245-G-A", gene="TNNT2", gene_id="ENSG00000118194",
            transcript="ENST00000656932", mane="NM_001276345.2", hgvsc="c.862C>T", hgvsp='p.Arg288Cys',
            consequence=('missense_variant',), exon="17/17", rsid='rs121964857',
            clinvar=ClinVar(
                classification="Likely benign",
                review_status="reviewed by expert panel", last_evaluated="2025-11-14",
                rcvs=('RCV000013222', 'RCV000036622', 'RCV000159322', 'RCV000162331', 'RCV000203739', 'RCV000248304'),
                conditions=('Hypertrophic cardiomyopathy',),
            ),
            aou={"eur": 0.00063, "afr": 0.00012, "amr": 0.00037, "sas": 1.1e-05, "mid": 0.00057, "oth": 0.00035},
            gnomad={"oth": (2, 2088), "amr": (6, 15274), "fin": (1, 10616), "eas": (0, 5188), "sas": (0, 4832), "asj": (0, 3472), "afr": (10, 41444), "nfe": (45, 68030)},
            splice_ai={"DS_AG": 0.01, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 10, "DP_AL": -9, "DP_DG": 2, "DP_DL": 10},
            matched=Matched(carriers_ac=0),
        ),
        Variant(
            vid="11-47335928-C-T", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.2686G>A", hgvsp='p.Val896Met',
            consequence=('missense_variant',), exon="26/35", rsid='rs35078470',
            clinvar=ClinVar(
                classification="Benign/Likely benign",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-06-01",
                rcvs=('RCV000035521', 'RCV000143915', 'RCV000204363', 'RCV000251320', 'RCV000602093', 'RCV000776054'),
                conditions=('Hypertrophic cardiomyopathy 4', 'Left ventricular noncompaction 10'),
            ),
            aou={"eur": 0.0062, "afr": 0.00043, "amr": 0.00055, "eas": 2.8e-05, "sas": 0.0008, "mid": 0.0061, "oth": 0.0053},
            gnomad={"oth": (7, 2116), "amr": (49, 15302), "fin": (287, 10608), "eas": (2, 5178), "sas": (1, 4830), "asj": (0, 3470), "afr": (20, 41568), "nfe": (503, 68016)},
            revel=0.214,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -29, "DP_AL": 5, "DP_DG": -48, "DP_DL": -34},
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="11-47337728-C-T", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.2375G>A", hgvsp='p.Trp792Ter',
            consequence=('stop_gained',), exon="24/35", rsid='rs2495750393',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-12-29",
                rcvs=('RCV004522990', 'RCV006488857', 'RCV006455855'),
                conditions=('Primary familial hypertrophic cardiomyopathy', 'Hypertrophic cardiomyopathy'),
            ),
            aou={"eur": 3, "oth": 1},
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -2, "DP_AL": 37, "DP_DG": 3, "DP_DL": -38},
            lof="HC",
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="11-47336013-T-C", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.2603-2A>G", hgvsp=None,
            consequence=('splice_acceptor_variant',), exon=None, intron="25/34", rsid='rs1419155559',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-10-21",
                rcvs=('RCV001183100', 'RCV001876083', 'RCV002429819', 'RCV004789434'),
                conditions=('Hypertrophic cardiomyopathy 4', 'Cardiomyopathy', 'Hypertrophic cardiomyopathy'),
            ),
            aou={"eur": 4, "amr": 1},
            gnomad=None,
            splice_ai={"DS_AG": 0.98, "DS_AL": 1, "DS_DG": 0, "DS_DL": 0, "DP_AG": -12, "DP_AL": -2, "DP_DG": -32, "DP_DL": -12},
            lof="HC",
            matched=Matched(carriers_ac=3),
        ),
        Variant(
            vid="11-47342867-CA-C", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.1419del", hgvsp='p.Phe473fs',
            consequence=('frameshift_variant',), exon="16/35", rsid=None,
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-05-25",
                rcvs=('RCV005203380', 'RCV005448133'),
                conditions=('Hypertrophic cardiomyopathy',),
            ),
            aou={"eur": 2},
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 30, "DP_AL": 43, "DP_DG": -37, "DP_DL": -8},
            lof="HC",
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="11-47347892-G-A", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.786C>T", hgvsp='p.Thr262=',
            consequence=('synonymous_variant',), exon="7/35", rsid='rs11570058',
            clinvar=ClinVar(
                classification="Benign",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-04",
                rcvs=('RCV000035669', 'RCV000247663', 'RCV000277368', 'RCV000317147', 'RCV000602389', 'RCV000776004'),
                conditions=('Left ventricular noncompaction 10', 'Cardiomyopathy', 'Hypertrophic cardiomyopathy 4'),
            ),
            aou={"eur": 0.12, "afr": 0.037, "amr": 0.045, "eas": 0.011, "sas": 0.064, "mid": 0.14, "oth": 0.11},
            gnomad={"oth": (169, 2114), "amr": (1117, 15300), "fin": (1246, 10602), "eas": (92, 5178), "sas": (280, 4830), "asj": (330, 3470), "afr": (1691, 41546), "nfe": (8423, 67978)},
            splice_ai={"DS_AG": 0, "DS_AL": 0.07, "DS_DG": 0, "DS_DL": 0.17, "DP_AG": -35, "DP_AL": 13, "DP_DG": 13, "DP_DL": -35},
            matched=Matched(carriers_ac=37, homozygotes=2),
        ),
        # Not in All of Us, so not in the VAT.
        Variant(
            vid="11-47349908-A-C", gene="MYBPC3", gene_id="ENSG00000134571",
            transcript="ENST00000545968", mane="NM_000256.3", hgvsc="c.520T>G", hgvsp='p.Phe174Val',
            consequence=('missense_variant',), exon="5/35", rsid=None,
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, single submitter", last_evaluated="2023-02-20",
                rcvs=('RCV006816162',),
                conditions=(),
            ),
            aou=None,
            gnomad=None,
            revel=0.7,
            splice_ai={"DS_AG": 0, "DS_AL": 0.02, "DS_DG": 0, "DS_DL": 0, "DP_AG": 14, "DP_AL": -7, "DP_DG": -44, "DP_DL": -7},
        ),
    ),
)
