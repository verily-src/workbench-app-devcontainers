# Data Collection Discovery

---

## When to Use This Skill

Read this skill whenever the user asks about finding, searching, or exploring data collections — whether inside their active workspace or across all of Workbench.

**Trigger phrases — platform-wide search only (read this skill):**
- "Find data collections across Workbench"
- "What data do I have access to?"
- "Search for [disease / modality / population] datasets"
- "Are there any genomics / clinical / imaging datasets I can use?"
- "Find me a dataset related to [topic]"
- "What data collections exist that I haven't added yet?"
- "Show me all accessible data"
- "Is there a [cancer / diabetes / cardiovascular] dataset available?"

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

## Step 3 — Present Results and Offer to Refine

Present matching collections in a clear summary. For each result, highlight the fields most relevant to the user's query. Example format:

---
**[Collection Name]**
- **Summary**: [shortDescription]
- **Data types**: [dataModalityTags]
- **Patients**: [patientCount] | **Time frame**: [timeFrame] | **Geography**: [geographicCoverage]
- **Access**: [availability] | Free: [isFree] | Instant: [isInstantlyAccessible]
- **View in Workbench**: [workbenchUrl]
---

After presenting results, ask:

> "Do any of these match what you're looking for? Would you like to refine the search — for example, filter by data type, study size, or access level?"

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

- The platform-wide search may not return every data collection in Workbench — some collections use different workspace tags. If the user knows a specific collection exists but it's not in the results, direct them to browse the full catalog at: `https://workbench.verily.com/data-collections`
- `workspace_list_data_collections` only shows collections already attached to the active workspace
- `platform_list_data_collections` searches platform-wide but requires the user to have at least READ access to the collection workspace
