"""
Tetralogy of Fallot: congenital heart disease genes (NKX2-5, TBX1, JAG1, GATA4, GATA6, TBX5,
FLT4, GDF1, ZFPM2), weighted toward variants of uncertain significance, every one a single
nucleotide change present in All of Us, and none departing from its cohort-wide frequency by
more than about 10x.

The story: eleven VUS, most of them missense but also a nonsense change in a last exon, a
synonymous change at a splice region, a splice-region intronic variant and a 5' UTR variant,
most with ClinVar records that name Tetralogy of Fallot. Three (NKX2-5, TBX1 and GATA6
missense) have three carriers each among the 214 matched participants against well under one
expected, enough for Review to call them enriched at about 8x. Most of the rest have one or two
carriers, a little above their expectation but short of a call: that includes the FLT4
pathogenic variant, a GDF1 VUS carried in trans with a P/LP variant by one participant (GDF1
being a recessive congenital heart gene), and a GATA4 VUS confined to African ancestry whose
ancestry-adjusted expectation is the honest comparison. Three rare variants, a likely
pathogenic GATA6 splice donor among them, have no matched carrier at all. Two common benign
variants give Review its other verdicts: a synonymous JAG1 variant at its All of Us frequency
(similar) and an intronic ZFPM2 variant seen in fewer participants than expected (depleted).

All of Us frequencies are synthetic and run somewhat above gnomAD genomes' for the rarer
variants, which is what lets a carrier or two sit within 10x of expectation; gnomAD's counts
are real. Variants checked against ClinVar and Ensembl VEP (MANE Select), 2026-11-02. SpliceAI,
REVEL and LOFTEE calls come from VEP's plugins; gnomAD counts are gnomAD v4 genomes', from its
API. The condition is the base fixture's 9000010, whose 214 participants that fixture owns.
"""

from .common import ClinVar, Condition, Matched, UseCase, Variant

CASE = UseCase(
    key="tetralogy_of_fallot",
    title="Tetralogy of Fallot",
    description="Congenital heart disease genes",
    condition=Condition(concept_id=9000010, name="Tetralogy of Fallot", est_count=205, participants=214, generate=False),
    ancestry={"EUR": 96, "AFR": 40, "AMR": 44, "OTH": 17, "EAS": 9, "SAS": 5, "MID": 3},
    age={"18–29": 61, "30–39": 57, "40–49": 44, "50–59": 30, "60–69": 17, "70+": 5},
    variants=(
        # NKX2-5 missense, REVEL 0.68, ClinVar names ToF. Three carriers against 0.4 expected (about 8x): enriched.
        Variant(
            vid="5-173232894-C-T", gene="NKX2-5", gene_id="ENSG00000183072",
            transcript="ENST00000329198", mane="NM_004387.4", hgvsc="c.650G>A", hgvsp='p.Arg217Lys',
            consequence=('missense_variant',), exon="2/2", rsid='rs751684900',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-04-23",
                rcvs=('RCV001315155', 'RCV005372639', 'RCV006557353'),
                conditions=('Atrial septal defect 7', 'Conotruncal heart malformations', 'Tetralogy of Fallot'),
            ),
            aou={"eur": 0.0015, "afr": 0.0003, "amr": 0.0007},
            gnomad={"oth": (0, 2094), "amr": (0, 15292), "fin": (1, 10618), "eas": (0, 5188), "sas": (0, 4838), "asj": (0, 3472), "afr": (0, 41462), "nfe": (2, 68038)},
            revel=0.676,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -2, "DP_AL": -1, "DP_DG": 4, "DP_DL": -19},
            matched=Matched(carriers_ac=3),
        ),
        # Seen mostly in South Asian ancestry (gnomAD agrees). One carrier: leans enriched, not called.
        Variant(
            vid="5-173232768-T-A", gene="NKX2-5", gene_id="ENSG00000183072",
            transcript="ENST00000329198", mane="NM_004387.4", hgvsc="c.776A>T", hgvsp='p.Tyr259Phe',
            consequence=('missense_variant',), exon="2/2", rsid='rs553883993',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-08-26",
                rcvs=('RCV002917418', 'RCV004066074', 'RCV004820920', 'RCV007011863'),
                conditions=('NKX2-5-related disorder', 'Atrial septal defect 7', 'Tetralogy of Fallot'),
            ),
            aou={"eur": 0.0002, "afr": 0.0006, "sas": 0.003},
            gnomad={"oth": (0, 2112), "amr": (0, 15312), "fin": (0, 10624), "eas": (0, 5178), "sas": (4, 4830), "asj": (0, 3470), "afr": (0, 41594), "nfe": (0, 68026)},
            revel=0.349,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -19, "DP_AL": -2, "DP_DG": 31, "DP_DL": 4},
            matched=Matched(carriers_ac=1),
        ),
        # TBX1 (22q11) missense, ClinVar names ToF. Three carriers against 0.4 expected: enriched.
        Variant(
            vid="22-19766732-T-G", gene="TBX1", gene_id="ENSG00000184058",
            transcript="ENST00000649276", mane="NM_001379200.1", hgvsc="c.1380T>G", hgvsp='p.His460Gln',
            consequence=('missense_variant',), exon="7/7", rsid='rs367711718',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-11-01",
                rcvs=('RCV001228940', 'RCV005029795', 'RCV005503035'),
                conditions=('DiGeorge syndrome', 'Conotruncal heart malformations', 'Tetralogy of Fallot'),
            ),
            aou={"eur": 0.0002, "afr": 0.0025, "amr": 0.0008, "oth": 0.001},
            gnomad={"oth": (0, 2092), "amr": (0, 15198), "fin": (0, 10424), "eas": (0, 5028), "sas": (1, 4804), "asj": (0, 3460), "afr": (4, 40990), "nfe": (4, 67692)},
            splice_ai={"DS_AG": 0.01, "DS_AL": 0, "DS_DG": 0.02, "DS_DL": 0, "DP_AG": 1, "DP_AL": 32, "DP_DG": 21, "DP_DL": 18},
            matched=Matched(carriers_ac=3),
        ),
        # Splice-region VUS three bases into the intron; SpliceAI sees nothing. One carrier.
        Variant(
            vid="22-19764329-G-A", gene="TBX1", gene_id="ENSG00000184058",
            transcript="ENST00000649276", mane="NM_001379200.1", hgvsc="c.711+3G>A", hgvsp=None,
            consequence=('splice_donor_region_variant', 'intron_variant'), exon=None, intron="3/6", rsid='rs376779775',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2024-10-16",
                rcvs=('RCV001930671', 'RCV002479395', 'RCV003892953'),
                conditions=('Tetralogy of Fallot', 'Conotruncal heart malformations', 'Velocardiofacial syndrome'),
            ),
            aou={"eur": 0.0001, "afr": 0.0012, "amr": 0.0005},
            gnomad={"oth": (0, 2116), "amr": (3, 15310), "fin": (0, 10632), "eas": (0, 5176), "sas": (0, 4828), "asj": (0, 3472), "afr": (7, 41592), "nfe": (1, 68032)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -43, "DP_AL": -41, "DP_DG": -3, "DP_DL": 50},
            matched=Matched(carriers_ac=1),
        ),
        # A nonsense variant ClinVar still calls VUS: last exon, so it escapes nonsense-mediated decay. One carrier.
        Variant(
            vid="20-10639518-G-A", gene="JAG1", gene_id="ENSG00000101384",
            transcript="ENST00000254958", mane="NM_000214.3", hgvsc="c.3637C>T", hgvsp='p.Arg1213Ter',
            consequence=('stop_gained',), exon="26/26", rsid='rs769276255',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2024-10-26",
                rcvs=('RCV001768276', 'RCV001868737', 'RCV002506808', 'RCV007006503'),
                conditions=('JAG1-related disorder', 'Charcot-Marie-Tooth disease, axonal, Type 2HH', 'Deafness, congenital heart defects, and posterior embryotoxon'),
            ),
            aou={"eur": 0.0004, "afr": 0.0003, "amr": 0.0002},
            gnomad={"oth": (0, 2088), "amr": (0, 15282), "fin": (0, 10614), "eas": (0, 5198), "sas": (0, 4832), "asj": (0, 3472), "afr": (1, 41416), "nfe": (2, 68034)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 16, "DP_AL": -46, "DP_DG": -49, "DP_DL": -46},
            lof="HC",
            matched=Matched(carriers_ac=1),
        ),
        # 5' UTR VUS, in All of Us but carried by no matched participant.
        Variant(
            vid="20-10673605-T-C", gene="JAG1", gene_id="ENSG00000101384",
            transcript="ENST00000254958", mane="NM_000214.3", hgvsc="c.-75A>G", hgvsp=None,
            consequence=('5_prime_UTR_variant',), exon="1/26", rsid='rs1208905634',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2021-12-29",
                rcvs=('RCV001138745', 'RCV002482265', 'RCV004694858'),
                conditions=('Isolated Nonsyndromic Congenital Heart Disease', 'Charcot-Marie-Tooth disease, axonal, Type 2HH', 'Deafness, congenital heart defects, and posterior embryotoxon'),
            ),
            aou={"eur": 0.00015, "amr": 0.0001},
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -37, "DP_AL": -19, "DP_DG": 48, "DP_DL": -50},
            matched=Matched(carriers_ac=0),
        ),
        # Common synonymous benign variant at its All of Us frequency (196 against 184 expected): Review calls it similar.
        Variant(
            vid="20-10652589-G-A", gene="JAG1", gene_id="ENSG00000101384",
            transcript="ENST00000254958", mane="NM_000214.3", hgvsc="c.765C>T", hgvsp='p.Tyr255=',
            consequence=('synonymous_variant',), exon="6/26", rsid='rs1131695',
            clinvar=ClinVar(
                classification="Benign",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-04",
                rcvs=('RCV000132569', 'RCV000199026', 'RCV000293317', 'RCV000254531', 'RCV001516693', 'RCV001730575'),
                conditions=('Isolated Nonsyndromic Congenital Heart Disease', 'Tetralogy of Fallot', 'Alagille syndrome due to a JAG1 point mutation'),
            ),
            aou={"eur": 0.44, "afr": 0.36, "amr": 0.46, "eas": 0.36, "sas": 0.53, "mid": 0.51, "oth": 0.46},
            gnomad={"oth": (979, 2092), "amr": (7000, 15272), "fin": (4749, 10530), "eas": (1768, 5146), "sas": (2574, 4832), "asj": (1747, 3472), "afr": (14674, 41434), "nfe": (31597, 67984)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 40, "DP_AL": -3, "DP_DG": -5, "DP_DL": -10},
            matched=Matched(carriers_ac=196, homozygotes=45),
        ),
        # African-ancestry VUS; the ancestry-adjusted expectation (40 AFR participants) is what to compare its one carrier with.
        Variant(
            vid="8-11708704-C-G", gene="GATA4", gene_id="ENSG00000136574",
            transcript="ENST00000532059", mane="NM_001308093.3", hgvsc="c.392C>G", hgvsp='p.Ala131Gly',
            consequence=('missense_variant',), exon="2/7", rsid='rs1013984246',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-19",
                rcvs=('RCV000493402', 'RCV001053521', 'RCV003224301', 'RCV003458166', 'RCV007037966'),
                conditions=('GATA4-related disorder', 'Ventricular septal defect 1', 'Atrioventricular septal defect 4'),
            ),
            aou={"afr": 0.0015, "amr": 0.0002, "oth": 0.0005},
            gnomad={"oth": (0, 2078), "amr": (0, 15188), "fin": (0, 10326), "eas": (0, 5178), "sas": (0, 4838), "asj": (0, 3466), "afr": (25, 41378), "nfe": (0, 67798)},
            revel=0.424,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 26, "DP_AL": 7, "DP_DG": 26, "DP_DL": -6},
            matched=Matched(carriers_ac=1),
        ),
        # Synonymous, but at a splice region (SpliceAI 0.09), which is why ClinVar keeps it a VUS. No matched carrier.
        Variant(
            vid="8-11757083-G-A", gene="GATA4", gene_id="ENSG00000136574",
            transcript="ENST00000532059", mane="NM_001308093.3", hgvsc="c.1149G>A", hgvsp='p.Gln383=',
            consequence=('splice_region_variant', 'synonymous_variant'), exon="6/7", rsid='rs751950851',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-01-14",
                rcvs=('RCV001771391', 'RCV002488595', 'RCV002540543'),
                conditions=('Atrioventricular septal defect 4', 'Atrial septal defect 2', 'Ventricular septal defect 1'),
            ),
            aou={"eur": 0.0003, "afr": 0.0002, "amr": 0.0002},
            gnomad={"oth": (0, 2094), "amr": (1, 15288), "fin": (0, 10624), "eas": (0, 5192), "sas": (0, 4836), "asj": (0, 3470), "afr": (1, 41474), "nfe": (2, 68044)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0.09, "DP_AG": 0, "DP_AL": -15, "DP_DG": -9, "DP_DL": 0},
            matched=Matched(carriers_ac=0),
        ),
        # GATA6 N-terminal missense. Three carriers against 0.34 expected (about 9x): enriched.
        Variant(
            vid="18-22171340-G-C", gene="GATA6", gene_id="ENSG00000141448",
            transcript="ENST00000269216", mane="NM_005257.6", hgvsc="c.196G>C", hgvsp='p.Asp66His',
            consequence=('missense_variant',), exon="2/7", rsid='rs554577705',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-03-25",
                rcvs=('RCV001866625', 'RCV007093545'),
                conditions=('Atrioventricular septal defect 5',),
            ),
            aou={"eur": 0.0012, "afr": 0.0005, "amr": 0.0006},
            gnomad={"oth": (0, 2112), "amr": (2, 15302), "fin": (0, 10608), "eas": (0, 5146), "sas": (0, 4830), "asj": (0, 3470), "afr": (1, 41562), "nfe": (0, 67974)},
            revel=0.455,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 47, "DP_AL": 9, "DP_DG": 5, "DP_DL": 45},
            matched=Matched(carriers_ac=3),
        ),
        # Likely pathogenic splice donor (SpliceAI 0.91), rare in All of Us and carried by no matched participant.
        Variant(
            vid="18-22172281-T-C", gene="GATA6", gene_id="ENSG00000141448",
            transcript="ENST00000269216", mane="NM_005257.6", hgvsc="c.1135+2T>C", hgvsp=None,
            consequence=('splice_donor_variant',), exon=None, intron="2/6", rsid=None,
            clinvar=ClinVar(
                classification="Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2024-03-18",
                rcvs=('RCV005026176', 'RCV005358184'),
                conditions=('Tetralogy of Fallot', 'Conotruncal heart malformations', 'Atrial septal defect 9'),
            ),
            aou={"eur": 0.0001, "afr": 0.0001},
            gnomad=None,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0.13, "DS_DL": 0.91, "DP_AG": 16, "DP_AL": -47, "DP_DG": 16, "DP_DL": -2},
            lof="HC",
            matched=Matched(carriers_ac=0),
        ),
        # TBX5 missense with a low REVEL (0.20): the VUS that probably isn't anything. One carrier.
        Variant(
            vid="12-114366299-G-T", gene="TBX5", gene_id="ENSG00000089225",
            transcript="ENST00000405440", mane="NM_181486.4", hgvsc="c.848C>A", hgvsp='p.Thr283Asn',
            consequence=('missense_variant',), exon="8/9", rsid='rs147077037',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2025-10-03",
                rcvs=('RCV000595942', 'RCV000619481', 'RCV001226522', 'RCV002483606'),
                conditions=('Aortic valve disease 2', 'Holt-Oram syndrome'),
            ),
            aou={"eur": 0.0008, "afr": 0.0002},
            gnomad={"oth": (0, 2094), "amr": (0, 15270), "fin": (0, 10616), "eas": (0, 5172), "sas": (0, 4824), "asj": (0, 3470), "afr": (1, 41414), "nfe": (8, 68032)},
            revel=0.203,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": -29, "DP_AL": -1, "DP_DG": -29, "DP_DL": 23},
            matched=Matched(carriers_ac=1),
        ),
        # FLT4 is the gene with the strongest ToF association. P/LP missense, REVEL 0.91, one carrier (about 6x).
        Variant(
            vid="5-180613051-C-T", gene="FLT4", gene_id="ENSG00000037280",
            transcript="ENST00000261937", mane="NM_182925.5", hgvsc="c.3391G>A", hgvsp='p.Gly1131Ser',
            consequence=('missense_variant',), exon="25/30", rsid='rs1554109707',
            clinvar=ClinVar(
                classification="Pathogenic/Likely pathogenic",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2024-12-13",
                rcvs=('RCV000622754', 'RCV005422870'),
                conditions=(),
            ),
            aou={"eur": 0.0006, "afr": 0.0001, "amr": 0.0003},
            gnomad={"oth": (0, 2110), "amr": (0, 15300), "fin": (0, 10622), "eas": (1, 5164), "sas": (0, 4830), "asj": (0, 3472), "afr": (0, 41542), "nfe": (1, 68014)},
            revel=0.912,
            splice_ai={"DS_AG": 0, "DS_AL": 0.02, "DS_DG": 0, "DS_DL": 0.05, "DP_AG": -40, "DP_AL": 33, "DP_DG": -8, "DP_DL": -40},
            matched=Matched(carriers_ac=1),
        ),
        # GDF1 is a recessive congenital heart gene; one of its two carriers has a P/LP GDF1 variant in trans, the compound-het case the in-trans column exists for.
        Variant(
            vid="19-18868731-G-A", gene="GDF1", gene_id="ENSG00000130283",
            transcript="ENST00000247005", mane="NM_001492.6", hgvsc="c.985C>T", hgvsp='p.Pro329Ser',
            consequence=('missense_variant',), exon="8/8", rsid='rs760908706',
            clinvar=ClinVar(
                classification="Uncertain significance",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-02",
                rcvs=('RCV002530186', 'RCV003419979', 'RCV004024189'),
                conditions=('GDF1-related disorder',),
            ),
            aou={"eur": 0.0012, "afr": 0.0002, "amr": 0.0006},
            gnomad={"oth": (0, 2102), "amr": (1, 15212), "fin": (0, 10114), "eas": (0, 5158), "sas": (0, 4828), "asj": (0, 3460), "afr": (0, 41440), "nfe": (5, 67728)},
            revel=0.444,
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 9, "DP_AL": -3, "DP_DG": 10, "DP_DL": 31},
            matched=Matched(carriers_ac=2, plp_in_trans=1),
        ),
        # Common intronic benign variant seen in fewer matched participants than its frequency predicts (232 against 265): Review calls it depleted.
        Variant(
            vid="8-105561350-C-T", gene="ZFPM2", gene_id="ENSG00000169946",
            transcript="ENST00000407775", mane="NM_012082.4", hgvsc="c.302-13C>T", hgvsp=None,
            consequence=('splice_polypyrimidine_tract_variant', 'intron_variant'), exon=None, intron="3/7", rsid='rs3735953',
            clinvar=ClinVar(
                classification="Benign/Likely benign",
                review_status="criteria provided, multiple submitters, no conflicts", last_evaluated="2026-02-03",
                rcvs=('RCV000254101', 'RCV001668526', 'RCV002058228', 'RCV002244630'),
                conditions=('46,XY sex reversal 9', 'Tetralogy of Fallot'),
            ),
            aou={"eur": 0.52, "afr": 0.81, "amr": 0.66, "eas": 0.54, "sas": 0.73, "mid": 0.52, "oth": 0.68},
            gnomad={"oth": (1389, 2110), "amr": (9347, 15242), "fin": (6034, 10544), "eas": (3067, 5158), "sas": (3423, 4816), "asj": (2137, 3470), "afr": (37803, 41518), "nfe": (39304, 67938)},
            splice_ai={"DS_AG": 0, "DS_AL": 0, "DS_DG": 0, "DS_DL": 0, "DP_AG": 13, "DP_AL": 16, "DP_DG": -25, "DP_DL": 13},
            matched=Matched(carriers_ac=232, homozygotes=63),
        ),
    ),
)
