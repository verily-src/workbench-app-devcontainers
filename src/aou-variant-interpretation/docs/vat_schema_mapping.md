# VAT schema → UI column mapping

Notes from reading  [Genomic Variant Store to Variant Annotation
Table design doc](https://docs.google.com/document/d/1CZQtrRDct9mLXRtL33F0Tq3SaIuzLZmTcO8mNXjC6vM/edit?tab=t.0#heading=h.wkmgb68p0pqh) and comparing against the columns actually rendered in the UI
(`ui/src/components/results/CohortVariantsPanel.tsx` and
`ui/src/components/results/ParticipantMatchedVariantsPanel.tsx`). The goal was to see how much
of the UI the VAT (Table 2 in the design doc) can support as designed, and call out what can't.

**Caveat:** this design doc is roughly 2 years out of date. Notably, LOFTEE was added to the VAT
after this doc was written, so its absence from Table 1/Table 2 below reflects the doc's
age, not an actual gap in today's VAT. Treat any "not in the VAT schema" note as "not in this
document" — worth confirming against the live VAT schema before treating it as real missing data.

Not all of these features are expected to be supported by what's in the VAT so far — e.g. ClinVar
P/LP in trans is known to require a lot of additional work (see below).

## Cross-cutting note

The VAT is at **variant-transcript** grain, but the UI is at **variant** grain. Every
transcript-specific field (gene, protein change, consequence) needs the canonical-transcript
collapse the design doc describes in Appendix C.1 / Table C.1 (pick `is_canonical_transcript =
true` + `transcript_source = Ensembl`, tie-break by consequence priority). That caveat applies to
every "same collapse" note below rather than being repeated per row.

## CohortVariantsPanel ("all participants" table)

| UI field | VAT source | Notes |
|---|---|---|
| `variant` | `vid` | Direct. |
| `gene` | `gene_symbol` (via canonical-transcript pick) | Needs the collapse step above. |
| `proteinChange` | `aa_change` (hgvsp) | Same collapse. |
| `consequence` | `consequence` (array) | Same collapse; also needs picking/rendering one value from the array. |
| `aouSubpopulation`/`aouAf`/`aouAc`/`aouAn` | `gvs_max_subpop`/`gvs_max_af`/`gvs_max_ac`/`gvs_max_an` | Direct — the VAT was designed with exactly this "max subpopulation" concept (Appendix G). |
| `gnomadSubpopulation`/`gnomadAf`/`gnomadAc`/`gnomadAn` | `gnomad_max_subpop`/`gnomad_max_af`/`gnomad_max_ac`/`gnomad_max_an` | Direct, same pattern. |
| ~~`gnomadUrl`~~ | — | Removed from the API. A function of `vid` alone, so the UI builds it (`utils/externalLinks.ts`); the frequency table shows it when the variant has gnomAD data (`gnomadSubpopulation` set). |
| `clinvarSignificance` | `clinvar_classification` (array) | VAT stores ClinVar's full submission vocabulary (Benign, Likely benign, Uncertain significance, Likely pathogenic, Pathogenic, conflicting, risk factor, etc.), unioned across submitters. Our 3-bucket `Pathogenic \| VUS \| Benign` taxonomy requires real collapsing logic, not a rename. |
| ~~`clinvarUrl`~~ | — | Removed from the API. VAT has no ClinVar accession/variation ID, and a search-by-coordinates URL is a function of `vid` alone, so the UI builds it (`utils/externalLinks.ts`) for every variant. |
| `spliceAi` (single score) | none directly — closest is 4 raw NIRVANA/SpliceAI fields: `splice_ai_acceptor_gain_score`, `_acceptor_loss_score`, `_donor_gain_score`, `_donor_loss_score` | VAT never collapses these to one number. Our single score needs a derivation (commonly max of the four) that isn't specified anywhere in the design doc. |
| `plof` (LOFTEE HC flag) | not in this design doc | LOFTEE isn't listed anywhere in Table 1's datasource list (NIRVANA, GVS, CADD, KEGG, GTEx, MGI, AoU subpop) or in Table 2 — but per team knowledge, LOFTEE was added to the VAT pipeline *after* this doc was written, so this isn't a real gap, just a stale doc. Confirm the current field name in the live VAT schema. |

## ParticipantMatchedVariantsPanel ("phenotype-matched" table)

| UI field | VAT source | Notes |
|---|---|---|
| `variant`, `gene`, `consequence` | same as above | Same caveats apply. |
| `cohortAc`/`cohortAn`/`cohortAf` | **none** | The doc is explicit: *"user defined cohort metrics will not be included in the VAT."* VAT only has whole-biobank (`gvs_all_*`) and ancestry-subpopulation (`gvs_<subpop>_*`) stats — nothing for an arbitrary phenotype-filtered participant subset. That requires querying genotype-level data directly (GVS or similar), since the VAT explicitly drops all sample/genotype info by design. |
| `homozygotes`/`heterozygotes` | **none** | Same root cause. Even for the *whole* cohort, Appendix H describes how to compute `n_het`/`n_homalt` but says plainly *"only sample_count is ever surfaced"* in the current design — this per-sample zygosity detail isn't planned to exist in the VAT at all, let alone for a filtered subgroup. |
| `clinvarPlpInTrans` | **none, by a wide margin** | Confirmed to be the biggest lift of anything here. It needs per-participant phased genotypes to know if a P/LP variant sits on the *other* allele (trans) — that's compound-het phasing across two variants per sample, which is categorically outside anything a variant-transcript aggregate table like the VAT can hold. This needs its own pipeline against raw per-sample genotype data, independent of the VAT entirely. |
| `afRatio` | derived (`cohortAf / gvs_all_af`) | The division itself is trivial once `cohortAf` exists — but `cohortAf` is the missing piece above, so this inherits that same gap. |

## Data source versions footer

`DataSourceVersionsController` lists All of Us CDRv8, gnomAD v3.1.2, ClinVar, SpliceAI, LOFTEE.
All but LOFTEE line up with the VAT's source list as documented (NIRVANA pulls in
gnomAD/ClinVar/SpliceAI; GVS/AoU supplies the AoU frequencies). LOFTEE isn't named anywhere in
this doc, but that's expected given it was added to the VAT after this doc was written.

## Bottom line

- The **all-participants table** (`CohortVariantsPanel`) is mostly well-covered by the VAT as
  designed — AoU/gnomAD frequency columns map almost 1:1. The main open item there is the
  link/URL fields (need building, not sourcing); `plof`/LOFTEE just needs confirming against the
  current live schema since it postdates this doc.
- The **phenotype-matched table** (`ParticipantMatchedVariantsPanel`) is the harder one:
  `cohortAc/An/Af`, `homozygotes`, `heterozygotes`, and especially `clinvarPlpInTrans` all require
  genotype-level access the VAT explicitly excludes by design ("genotype information is dropped in
  this design"). None of that is a VAT gap to fix — it's a fundamentally different data source
  (raw/phased genotypes) that the VAT was never meant to provide.
