# Data Collection Discovery

---

## When to Use This Skill

**Always read this skill before calling `platform_list_data_collections`.** This skill controls the full discovery flow — do not call the MCP tool directly without following these steps first.

Do NOT read this skill if the user is asking about data already in their workspace. In that case, call `workspace_list_data_collections` directly.

**Read this skill ONLY when the user says something like:**
- "Search all data collections I have access to"
- "Find data collections across Workbench"
- "What data collections can I add to my workspace?"
- "Are there any data collections I haven't added yet?"
- "Find a data collection related to [topic / disease / modality]"
- "Search across all Workbench data collections for [keyword]"
- "What data collections are available on the platform?"
- "Browse all accessible data collections"

**Listing data collections in my workspace** — do NOT read this skill, call `workspace_list_data_collections` directly:
- "What data collections are in my workspace?"
- "What data is attached to my workspace?"
- "List the data collections I have"
- "What datasets do I have in this workspace?"
- "Show me the data collections in my workspace"

---

## Step 0 — Clarify the Search Scope

**If the user's intent is ambiguous** (e.g., they said "find me data" without specifying where), ask:

> "Would you like me to search only within your active workspace, or search across all data collections you have access to in Workbench (platform-wide)?"

- **Workspace-only**: Call `workspace_list_data_collections` directly — no need to continue with this skill
- **Platform-wide**: Continue with Steps 1–4 below

If the user clearly said "in my workspace" or asked about attached resources, skip this skill entirely and call `workspace_list_data_collections` directly.

---

## Step 1 — Clarify Search Criteria

Before searching, confirm what the user is looking for:

- **Topic / disease area** (e.g., oncology, cardiovascular, diabetes, general health)
- **Data modality** (e.g., genomics, imaging, lab results, patient-reported outcomes, EHR/EHR-derived)
- **Population** (e.g., age range, geography, study size)
- **Access type** (free vs. controlled access, instantly accessible vs. requires approval)
- **Data model** (e.g., standard underlay like AoU, custom schema)

If the user has already provided enough context, proceed directly to Step 2.

---

## Step 2 — Search

### Platform-wide search (primary)

Use the MCP tool first:

```
mcp__wb__platform_list_data_collections(query="<keyword>")
```

- Pass the user's topic, modality, or disease area as `query`
- The tool searches across: name, description, modality tags, therapeutic tags, data model
- If no `query` is provided, it returns all accessible data collections

If the MCP tool is unavailable, fall back to:
```bash
wb workspace list --format=json | jq '[.[] | select(.properties[]? | select(.key=="terra-type" and .value=="data-collection"))]'
```

### Workspace-scoped search

```
mcp__wb__workspace_list_data_collections()
```

### Search across all returned metadata

For each result, the tool returns the following fields — use ALL of them when evaluating relevance:

| Field | What it tells you |
|---|---|
| `name` | Collection name |
| `shortDescription` | One-line summary |
| `description` | Full overview including provenance and methodology |
| `organization` | Who owns the data |
| `availability` | Public open access / Public controlled access / Private |
| `isFree` | Whether access is free |
| `isInstantlyAccessible` | Whether access is immediate or requires approval |
| `patientCount` | Study size |
| `timeFrame` | Date range of data collection |
| `geographicCoverage` | Countries / regions |
| `dataModel` | Schema type (e.g., standard underlay, Non-standard custom) |
| `dataModalityTags` | Types of data (imaging, lab-results, ecrf, genomics, etc.) |
| `therapeuticTags` | Disease/health areas (oncology, general-health, etc.) |
| `underlayName` | Data model identifier — use with `underlay_list_entities` for schema exploration |
| `dataDictionary` | Links to schema documentation |
| `usageExamples` | Sample use cases and SQL queries |
| `accessGroupName` | Access group required |
| `supportEmail` | Who to contact |
| `workbenchUrl` | Direct link to the collection in the Workbench UI |

---

## Step 3 — Rank, Present Results, and Offer to Refine

For every result returned, assign a **relevance score from 1–5** based on how well the collection's metadata matches the user's query. Use ALL available metadata fields when scoring — name, description, shortDescription, dataModalityTags, therapeuticTags, dataModel, usageExamples, dataDictionary, patientCount, geographicCoverage.

**Scoring guide:**
| Score | Meaning |
|---|---|
| ⭐⭐⭐⭐⭐ 5 | Exact match — directly contains the data type, gene, disease, or topic the user asked about |
| ⭐⭐⭐⭐ 4 | Strong match — highly relevant to the query and covers the right domain or modality |
| ⭐⭐⭐ 3 | Good match — related to the query's domain; may not be specific to the exact topic but offers valuable context |
| ⭐⭐ 2 | Potential match — shares topical overlap with the query and is worth exploring further |
| ⭐ 1 | Broad match — loosely connected to the query; included for completeness and may surface unexpected value |

Present results **sorted by score (highest first)**. For each result, include a one-sentence justification for the score that explains concretely why it ranked that way. Example format:

---
**[Collection Name]** — ⭐⭐⭐⭐⭐ 5/5
- **Why**: [One concrete sentence explaining what in the metadata drove this score — e.g. "Contains whole-genome sequencing data with BRCA1/BRCA2 variant calls across 10,000 patients."]
- **Summary**: [shortDescription]
- **Data types**: [dataModalityTags]
- **Patients**: [patientCount] | **Time frame**: [timeFrame] | **Geography**: [geographicCoverage]
- **Access**: [availability] | Free: [isFree] | Instant: [isInstantlyAccessible]
- **View in Workbench**: [workbenchUrl]
---

After presenting results, ask:

> "Do any of these look useful? Would you like to refine the search or explore a specific collection in more detail?"

If the user wants deeper detail on a specific collection:
- Use `underlayName` with `mcp__wb__underlay_list_entities` to explore the data schema
- Reference `usageExamples` for sample queries
- Reference `dataDictionary` for table/field documentation

---

## Step 4 — Add to Workspace

If the user wants to use a data collection:

1. Provide the direct link to the collection:
   > "You can view and request access to **[Collection Name]** here: [workbenchUrl]"

2. Instruct them to click **"Add to Workspace"** or **"Get Access"** in the Workbench UI. The button label depends on whether the collection is instantly accessible or requires approval.

3. If the collection is instantly accessible (`isInstantlyAccessible: true`), tell them:
   > "This collection is instantly accessible — once you click 'Add to Workspace', the resources will be available in your workspace immediately."

4. If it requires approval (`isInstantlyAccessible: false`):
   > "This collection requires access approval. After you submit the request at [workbenchUrl], access is typically granted after review."

5. After the user confirms they've added the collection, use `workspace_list_data_collections` to confirm the resources are now visible in their workspace.

---

## Notes

- `workspace_list_data_collections` only shows collections already attached to the active workspace
- `platform_list_data_collections` searches platform-wide but requires the user to have at least READ access to the collection workspace
