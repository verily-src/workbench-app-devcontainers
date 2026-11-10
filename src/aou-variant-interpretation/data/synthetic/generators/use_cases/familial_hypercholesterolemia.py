"""
Familial hypercholesterolemia: LDLR, APOB and PCSK9.

The story: LDLR loss of function -- two nonsense variants (one of which also disrupts splicing),
a frameshift and a splice donor variant -- and expert-panel LDLR missense variants are enriched in
the matched cohort, as is APOB's familial defective apoB variant (p.Arg3527Gln). PCSK9 runs the
other way: its loss of function lowers LDL, so the common p.Arg46Leu and two nonsense variants
common in African ancestry are depleted among people with FH. A very common LDLR synonymous
variant and a benign LDLR missense variant sit at background, and a conflicting APOB variant is
modestly enriched. One LDLR VUS is enriched; another isn't in All of Us.

Variants checked against ClinVar and Ensembl VEP (MANE Select), 2026-09-29. SpliceAI, REVEL and
LOFTEE calls come from VEP's plugins; gnomAD counts are gnomAD v4 genomes', from its API.
"""

from .common import ClinVar, Condition, Matched, UseCase, Variant

CASE = UseCase(
    key="familial_hypercholesterolemia",
    title="Familial hypercholesterolemia",
    description="LDLR, APOB and PCSK9",
    condition=Condition(concept_id=9000050, name="Familial hypercholesterolemia", est_count=386, participants=391, synonyms=('fh', 'familial hypercholesterolaemia', 'heterozygous familial hypercholesterolemia')),
    ancestry={"EUR": 204, "AFR": 74, "AMR": 62, "OTH": 26, "EAS": 12, "SAS": 9, "MID": 4},
    age={"18–29": 14, "30–39": 38, "40–49": 72, "50–59": 104, "60–69": 98, "70+": 65},
    variants=(
        Variant(
            vid="19-11116928-G-A", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.1775G>A", hgvsp='p.Gly592Glu',
            consequence=('missense_variant',), exon="12/18", rsid='rs137929307',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="reviewed by expert panel", last_evaluated="2021-06-09",
                rcvs=('RCV000172964', 'RCV000162001', 'RCV000587007', 'RCV000844730', 'RCV002051664', 'RCV002399517'),
                conditions=('Hypercholesterolemia, familial, 1',),
            ),
            aou={"eur": 9, "oth": 1},
            gnomad={"oth": (2, 2084), "amr": (0, 15230), "fin": (0, 10592), "eas": (0, 5186), "sas": (0, 4824), "asj": (0, 3468), "afr": (0, 41448), "nfe": (5, 68022)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 2, "DP_AL": -14, "DP_DG": 36, "DP_DL": 49},
            matched=Matched(carriers_ac=5),
        ),
        Variant(
            vid="19-11120425-C-A", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.2043C>A", hgvsp='p.Cys681Ter',
            consequence=('stop_gained',), exon="14/18", rsid='rs121908031',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-03-26",
                rcvs=('RCV000003887', 'RCV000481771', 'RCV000590806', 'RCV000844750', 'RCV002415394', 'RCV004584310'),
                conditions=('Hypercholesterolemia, familial, 1', 'Homozygous familial hypercholesterolemia'),
            ),
            aou={"eur": 3},
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0.04, "DS_DG": 0, "DS_DL": 0, "DP_AG": -36, "DP_AL": 16, "DP_DG": -4, "DP_DL": -10},
            lof="HC",
            matched=Matched(carriers_ac=3),
        ),
        Variant(
            vid="2-21006288-C-T", gene="APOB", gene_id="ENSG00000084674",
            transcript="ENST00000233242", mane="NM_000384.3", hgvsc="c.10580G>A", hgvsp='p.Arg3527Gln',
            consequence=('missense_variant',), exon="26/29", rsid='rs5742904',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-08-06",
                rcvs=('RCV000019479', 'RCV000254882', 'RCV000412515', 'RCV000499833', 'RCV000851289', 'RCV000771116'),
                conditions=('Familial hypercholesterolemia', 'Homozygous familial hypercholesterolemia'),
            ),
            aou={"eur": 0.00044, "afr": 0.00012, "amr": 4.5e-05, "eas": 5e-05, "mid": 0.00044, "oth": 0.00025},
            gnomad={"oth": (1, 2088), "amr": (5, 15270), "fin": (0, 10610), "eas": (0, 5190), "sas": (0, 4822), "asj": (0, 3468), "afr": (5, 41414), "nfe": (32, 68014)},
            revel=0.735,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -2, "DP_AL": 48, "DP_DG": 37, "DP_DL": 0},
            matched=Matched(carriers_ac=4),
        ),
        # Protective: loss of PCSK9 lowers LDL, so it's depleted among people with FH.
        Variant(
            vid="1-55039974-G-T", gene="PCSK9", gene_id="ENSG00000169174",
            transcript="ENST00000302118", mane="NM_174936.4", hgvsc="c.137G>T", hgvsp='p.Arg46Leu',
            consequence=('missense_variant',), exon="1/12", rsid='rs11591147',
            clinvar=ClinVar(
                classification="Benign/Likely benign",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-03",
                rcvs=('RCV000003012', 'RCV000203182', 'RCV000256313', 'RCV000508774', 'RCV000605465', 'RCV000985896'),
                conditions=('Familial hypercholesterolemia', 'Hypobetalipoproteinemia'),
            ),
            aou={"eur": 0.018, "afr": 0.0024, "amr": 0.0076, "sas": 0.0011, "mid": 0.017, "oth": 0.012},
            gnomad={"oth": (27, 2116), "amr": (133, 15312), "fin": (467, 10630), "eas": (0, 5188), "sas": (4, 4832), "asj": (16, 3472), "afr": (109, 41602), "nfe": (1104, 68046)},
            revel=0.028,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 11, "DP_AL": -43, "DP_DG": 33, "DP_DL": -6},
            matched=Matched(carriers_ac=3),
        ),
        Variant(
            vid="19-11123297-C-A", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.2264C>A", hgvsp='p.Ala755Asp',
            consequence=('missense_variant',), exon="15/18", rsid=None,
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, single submitter", last_evaluated="2019-12-17",
                rcvs=('RCV006886674',),
                conditions=(),
            ),
            aou={"afr": 3},
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 10, "DP_AL": 48, "DP_DG": 47, "DP_DL": -2},
            matched=Matched(carriers_ac=1),
        ),
        Variant(
            vid="19-11120436-C-T", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.2054C>T", hgvsp='p.Pro685Leu',
            consequence=('missense_variant',), exon="14/18", rsid='rs28942084',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-07-20",
                rcvs=('RCV000003891', 'RCV000162007', 'RCV000775085', 'RCV000844731', 'RCV002415395', 'RCV004745144'),
                conditions=('Familial hypercholesterolemia', 'Homozygous familial hypercholesterolemia'),
            ),
            aou={"eur": 5, "oth": 1},
            gnomad={"oth": (0, 2090), "amr": (0, 15270), "fin": (0, 10626), "eas": (0, 5196), "sas": (0, 4834), "asj": (0, 3472), "afr": (3, 41456), "nfe": (3, 68042)},
            splice_ai={"DS_AG": 0, "DS_AL": 0.02, "DS_DG": 0, "DS_DL": 0, "DP_AG": -47, "DP_AL": 5, "DP_DG": 47, "DP_DL": -21},
            matched=Matched(carriers_ac=3),
        ),
        Variant(
            vid="19-11102774-G-A", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.301G>A", hgvsp='p.Glu101Lys',
            consequence=('missense_variant',), exon="3/18", rsid='rs144172724',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="reviewed by expert panel", last_evaluated="2021-12-13",
                rcvs=('RCV000162016', 'RCV000211583', 'RCV000775032', 'RCV000844744', 'RCV002051659', 'RCV002433637'),
                conditions=('Hypercholesterolemia, familial, 1',),
            ),
            aou={"eur": 3, "amr": 1},
            gnomad={"oth": (0, 2090), "amr": (0, 15256), "fin": (0, 10614), "eas": (0, 5192), "sas": (1, 4832), "asj": (0, 3472), "afr": (1, 41452), "nfe": (1, 68044)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 12, "DP_AL": -45, "DP_DG": -38, "DP_DL": 12},
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="19-11123210-C-T", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.2177C>T", hgvsp='p.Thr726Ile',
            consequence=('missense_variant',), exon="15/18", rsid='rs45508991',
            clinvar=ClinVar(
                classification="Benign",
                review_status="reviewed by expert panel", last_evaluated="2022-05-24",
                rcvs=('RCV000030134', 'RCV000162011', 'RCV000247593', 'RCV000771082', 'RCV002426526'),
                conditions=('Hypercholesterolemia, familial, 1',),
            ),
            aou={"eur": 0.0081, "afr": 0.00083, "amr": 0.0024, "sas": 9.6e-05, "mid": 0.0076, "oth": 0.0056},
            gnomad={"oth": (13, 2114), "amr": (42, 15266), "fin": (106, 10620), "eas": (0, 5184), "sas": (0, 4822), "asj": (10, 3468), "afr": (41, 41556), "nfe": (537, 68020)},
            splice_ai={"DS_AG": 0.01, "DS_AL": 0, "DS_DG": 0.01, "DS_DL": 0, "DP_AG": -34, "DP_AL": -28, "DP_DG": 13, "DP_DL": -34},
            matched=Matched(carriers_ac=7),
        ),
        # Protective loss of function, common in African ancestry: absent from the matched cohort.
        Variant(
            vid="1-55046549-C-G", gene="PCSK9", gene_id="ENSG00000169174",
            transcript="ENST00000302118", mane="NM_174936.4", hgvsc="c.426C>G", hgvsp='p.Tyr142Ter',
            consequence=('stop_gained',), exon="3/12", rsid='rs67608943',
            clinvar=ClinVar(
                classification="Conflicting classifications of pathogenicity",
                review_status="criteria provided, conflicting classifications", last_evaluated="2026-08-01",
                rcvs=('RCV000003010', 'RCV000588335', 'RCV001191121', 'RCV001097394', 'RCV001731276', 'RCV004658956'),
                rcv_classifications=('Likely benign', 'Pathogenic', 'Uncertain significance', 'Benign', 'Uncertain significance', 'Likely benign'),
                conditions=('Hypercholesterolemia, autosomal dominant, 3', 'Familial hypercholesterolemia'),
            ),
            aou={"afr": 0.0045, "amr": 0.0003, "oth": 0.0008},
            gnomad={"oth": (2, 2112), "amr": (3, 15310), "fin": (0, 10624), "eas": (0, 5168), "sas": (0, 4824), "asj": (0, 3468), "afr": (120, 41574), "nfe": (0, 68020)},
            splice_ai={"DS_AG": 0.04, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 1, "DP_AL": -26, "DP_DG": 1, "DP_DL": -17},
            lof="HC",
            matched=Matched(carriers_ac=0),
        ),
        # Protective loss of function, common in African ancestry: depleted among the matched.
        Variant(
            vid="1-55063542-C-A", gene="PCSK9", gene_id="ENSG00000169174",
            transcript="ENST00000302118", mane="NM_174936.4", hgvsc="c.2037C>A", hgvsp='p.Cys679Ter',
            consequence=('stop_gained',), exon="12/12", rsid='rs28362286',
            clinvar=ClinVar(
                classification="Conflicting classifications of pathogenicity",
                review_status="criteria provided, conflicting classifications", last_evaluated="2026-06-15",
                rcvs=('RCV000003011', 'RCV000508694', 'RCV000531428', 'RCV000771132', 'RCV001731277', 'RCV001508868'),
                rcv_classifications=('Likely benign', 'Pathogenic', 'Benign', 'Uncertain significance', 'Uncertain significance', 'Likely benign'),
                conditions=('Hypercholesterolemia, autosomal dominant, 3', 'Familial hypercholesterolemia'),
            ),
            aou={"eur": 4.7e-06, "afr": 0.0091, "amr": 0.00023, "sas": 2.5e-05, "mid": 5.1e-06, "oth": 0.0005},
            gnomad={"oth": (1, 2116), "amr": (2, 15312), "fin": (0, 10632), "eas": (0, 5182), "sas": (0, 4826), "asj": (0, 3470), "afr": (353, 41592), "nfe": (3, 68024)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -43, "DP_AL": 38, "DP_DG": 12, "DP_DL": 38},
            lof="HC",
            lof_flags=('PHYLOCSF_WEAK',),
            matched=Matched(carriers_ac=1),
        ),
        Variant(
            vid="2-21006196-G-A", gene="APOB", gene_id="ENSG00000084674",
            transcript="ENST00000233242", mane="NM_000384.3", hgvsc="c.10672C>T", hgvsp='p.Arg3558Cys',
            consequence=('missense_variant',), exon="26/29", rsid='rs12713559',
            clinvar=ClinVar(
                classification="Conflicting classifications of pathogenicity",
                review_status="criteria provided, conflicting classifications", last_evaluated="2026-08-21",
                rcvs=('RCV000019486', 'RCV000219069', 'RCV000412657', 'RCV000587550', 'RCV001837440', 'RCV002408470'),
                rcv_classifications=('Uncertain significance', 'Likely pathogenic', 'Uncertain significance', 'Likely benign', 'Uncertain significance', 'Benign'),
                conditions=('Hypercholesterolemia, autosomal dominant, type B', 'Familial hypercholesterolemia'),
            ),
            aou={"eur": 0.00092, "afr": 0.00045, "amr": 0.00024, "eas": 4.7e-05, "sas": 1.1e-05, "mid": 0.00087, "oth": 0.00088},
            gnomad={"oth": (1, 2112), "amr": (8, 15298), "fin": (0, 10614), "eas": (0, 5176), "sas": (0, 4826), "asj": (2, 3472), "afr": (28, 41552), "nfe": (37, 68020)},
            revel=0.792,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 42, "DP_AL": -45, "DP_DG": 37, "DP_DL": -24},
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="19-11089616-G-A", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.67+1G>A", hgvsp=None,
            consequence=('splice_donor_variant',), exon=None, intron="1/17", rsid='rs762417023',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-01-03",
                rcvs=('RCV000497129', 'RCV003581669', 'RCV005348139', 'RCV004017650', 'RCV005431709'),
                conditions=('Familial hypercholesterolemia', 'Homozygous familial hypercholesterolemia', 'Hypercholesterolemia, familial, 1'),
            ),
            aou={"eur": 2, "amr": 1},
            gnomad={"oth": (0, 2094), "amr": (0, 15278), "fin": (0, 10620), "eas": (0, 5190), "sas": (0, 4826), "asj": (0, 3468), "afr": (1, 41446), "nfe": (0, 68032)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0.46, "DS_DL": 0.99, "DP_AG": 0, "DP_AL": 20, "DP_DG": 27, "DP_DL": -1},
            lof="HC",
            matched=Matched(carriers_ac=2),
        ),
        Variant(
            vid="19-11105540-TC-T", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.636del", hgvsp='p.Ser213fs',
            consequence=('frameshift_variant',), exon="4/18", rsid=None,
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-04-21",
                rcvs=('RCV006637499', 'RCV006708854'),
                conditions=('Familial hypercholesterolemia', 'Hypercholesterolemia, familial, 1'),
            ),
            aou={"eur": 2},
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -11, "DP_AL": 5, "DP_DG": -11, "DP_DL": -15},
            lof="HC",
            matched=Matched(carriers_ac=2),
        ),
        # A nonsense variant that also disrupts splicing, as its SpliceAI score shows.
        Variant(
            vid="19-11120413-C-A", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.2031C>A", hgvsp='p.Cys677Ter',
            consequence=('stop_gained',), exon="14/18", rsid='rs2512430551',
            clinvar=ClinVar(
                classification="Pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-11-24",
                rcvs=('RCV003477289', 'RCV005356447', 'RCV005871182', 'RCV006473275'),
                conditions=('Familial hypercholesterolemia', 'Hypercholesterolemia, familial, 1'),
            ),
            aou={"eur": 3, "oth": 1},
            gnomad=None,
            splice_ai={"DS_AG": 0.65, "DS_AL": 0.21, "DS_DG": 0, "DS_DL": 0, "DP_AG": 28, "DP_AL": -43, "DP_DG": 2, "DP_DL": -34},
            lof="HC",
            matched=Matched(carriers_ac=3),
        ),
        Variant(
            vid="19-11120205-T-C", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.1959T>C", hgvsp='p.Val653=',
            consequence=('synonymous_variant',), exon="13/18", rsid='rs5925',
            clinvar=ClinVar(
                classification="Benign/Likely benign",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-04",
                rcvs=('RCV000238160', 'RCV000244560', 'RCV001275782', 'RCV001812662', 'RCV002418056'),
                conditions=('Familial hypercholesterolemia', 'Hypercholesterolemia, familial, 1'),
            ),
            aou={"eur": 0.46, "afr": 0.17, "amr": 0.51, "eas": 0.18, "sas": 0.42, "mid": 0.42, "oth": 0.41},
            gnomad={"oth": (828, 2110), "amr": (7720, 15240), "fin": (5251, 10558), "eas": (1116, 5160), "sas": (2097, 4820), "asj": (1458, 3470), "afr": (8444, 41474), "nfe": (29861, 67936)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -10, "DP_AL": 22, "DP_DG": 34, "DP_DL": 38},
            matched=Matched(carriers_ac=309, homozygotes=61),
        ),
        # Not in All of Us, so not in the VAT.
        Variant(
            vid="19-11116132-T-A", gene="LDLR", gene_id="ENSG00000130164",
            transcript="ENST00000558518", mane="NM_000527.5", hgvsc="c.1625T>A", hgvsp='p.Ile542Asn',
            consequence=('missense_variant',), exon="11/18", rsid=None,
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, single submitter", last_evaluated="2022-10-14",
                rcvs=('RCV006886669',),
                conditions=(),
            ),
            aou=None,
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 9, "DP_AL": -1, "DP_DG": 20, "DP_DL": 40},
        ),
    ),
)
