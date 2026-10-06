# Solution Overview and Executive Summary: SatQuery AI

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-001 |
| **Document Title** | Solution Overview and Executive Summary |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Organization** | Indian Space Research Organisation (ISRO), Department of Space |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

---

## 2. EXECUTIVE SUMMARY

### 2.1 Core Principle

> **Query - Evidence - Understanding** ("From Pixels to Evidence to Understanding")

SatQuery AI converts a natural-language earth observation (EO) question into a validated, capability-aware workflow:

- **Deterministic tools** provide measurements (spectral indices, SAR backscatter analysis, temporal statistics).
- **Specialist models** provide perception and interpretation (EarthMind-4B, MCD-Mamba and optional grounding models).
- **Geospatial processing** gives every output spatial meaning (coordinate systems, geometry, area, GeoJSON).
- **The Evidence Engine** connects, validates and verifies the results before the answer is presented.

### 2.2 Problem Addressed

EO data spans optical, multispectral and SAR modalities at resolutions from sub-metre (Cartosat) to tens of metres (Sentinel). Extracting information requires expertise in sensors, spectral bands, polarizations, coordinate systems, pair registration and model selection, and existing remote sensing AI tools are single-task systems. Vision-language models alone can state figures and locations without evidence. SatQuery lets a user ask a question in natural language, in English or an Indian language, and receive an answer that is supported by measured, traceable evidence, or a clear statement of why the data cannot support an answer.

### 2.3 Solution Summary

SatQuery orchestrates a registry of remote sensing models and tools behind a single conversational interface. A LangGraph orchestrator understands the query, assesses the available data, selects tools and models, executes the plan and passes the outputs to an evidence layer that aggregates, validates and records provenance. EarthMind then acts as an AI Analyst that explains the validated evidence, and claim verification checks the final answer before it is presented together with a map, evidence cards and an execution trace.

---

## 3. PROBLEM ANALYSIS

### 3.1 Stakeholder Needs

| Stakeholder | Need | SatQuery Response |
| :--- | :--- | :--- |
| ISRO analysts | Faster, auditable analysis | Validated workflows with evidence records and traces |
| NDRF and disaster management officers | Rapid flood and damage assessment, often under cloud cover | SAR-based and optical-SAR analysis; external hazard data (FIRMS, EONET, IMD radar) |
| Public researchers | Reproducible analysis | Evidence store with parameters, versions and reproducible reports |
| Agricultural and regional officers | Vegetation and land-use change in their own language | Spectral and temporal tools; multilingual queries |

### 3.2 Gap Analysis

1. Single-task tools that users must combine manually.
2. No capability-aware planning from question to required evidence.
3. Weak joint reasoning over optical and SAR imagery.
4. Loss of band and polarization semantics when imagery is converted for models.
5. Unsupported numerical and spatial statements from vision-language models.
6. English-only interfaces that exclude many field users.

---

## 4. PROPOSED SOLUTION

### 4.1 Core Capabilities

| No. | Capability | Scope | Prototype Status |
|---|---|---|---|
| 1 | Single-image VQA for supported optical, multispectral and SAR inputs | Core | In Progress |
| 2 | Scene captioning and description | Core | In Progress |
| 3 | Text-guided grounding (text to region) | Core | In Progress |
| 4 | Bi-temporal change detection and change VQA (MCD-Mamba to EarthMind pipeline) | Core | In Progress |
| 5 | Optical-SAR analysis with explicit agreement and disagreement | Core | In Progress |
| 6 | Deterministic spectral indices and SAR and temporal analysis | Core | Planned |
| 7 | Geospatial masks, vectors, areas and coordinates | Core | Implemented (footprints); Planned (vector outputs) |
| 8 | Session-aware follow-up questions | Core | Implemented |
| 9 | Safe failure when data cannot support a claim | Core | Implemented (input and pair validation) |
| 10 | Auditable evidence and execution trace | Core | In Progress |
| 11 | Multilingual queries and answers | Optional | Planned |
| 12 | External model integration through the capability registry | Optional | In Progress (contract and model services) |
| 13 | External data connectors | Future | Planned |

### 4.2 Model Responsibilities

**EarthMind-4B - core VLM:** semantic EO understanding, VQA, captioning, location reasoning and multimodal reasoning; also the AI Analyst that interprets validated evidence and writes the final explanation.

**MCD-Mamba - core change specialist:** change probability and mask, and spatial change evidence. A change mask alone does not establish semantic transitions such as vegetation to building; these require EarthMind interpretation backed by spectral evidence (see Section 4.3).

**GeoGround - optional:** remote sensing visual grounding, enabled only if evaluation shows a clear advantage.

**Additional specialists (optional or experimental):** Grounding DINO and SAM2 for open-vocabulary detection and segmentation; TACMT for SAR grounding; DoFA and RSUniVLM as candidate alternatives, admitted through the evaluation harness.

### 4.3 MCD-Mamba to EarthMind Pipeline

Change questions are answered by a two-stage pipeline in which MCD-Mamba determines **where** change occurred and EarthMind explains **what** changed, using only validated evidence:

```text
T1 + T2
  -> input validation and Registration Quality Gate
  -> MCD-Mamba: change probability and mask
  -> post-processing: regions, area, statistics (EvidenceRecords)
  -> deterministic evidence for attribution: dNDVI, dNDBI, dMNDWI, SAR backscatter change
  -> evidence aggregation and validation
  -> EarthMind AI Analyst: T1, T2, change overlay and evidence summary -> explanation
  -> claim verification -> answer, change map, evidence cards, trace
```

Full specification: `05_technical_design.md` Section 7; full-system flow in Section 2.

### 4.4 Key Differentiators

- **Capability-aware planning:** query, required capabilities, evidence requirements, workflow, then tools and models.
- **Evidence Engine:** every output becomes an EvidenceRecord with provenance and parent links.
- **Evidence-backed VLM reasoning:** EarthMind interprets; quantitative and geospatial claims are verified against evidence.
- **Cross-modal evidence fusion:** optical and SAR compared, disagreement shown as uncertainty.
- **Safe failure:** qualified failure instead of confident guessing.
- **Open integration:** external models and data sources join through the same registry contract and are enabled only after evaluation.
- **Multilingual access:** queries in Indian languages, answers returned in the user's language with measurements preserved exactly.

### 4.5 Supported Configurations

| Configuration | Status |
|---|---|
| Single optical, multispectral or SAR image | Upload and validation Implemented; analysis In Progress |
| Co-registered optical and SAR pair | Validation workflow defined; analysis In Progress |
| T1 / T2 bi-temporal pair | Upload and pair check Implemented; analysis In Progress |
| Change VQA using T1, T2 and change evidence | Planned |
| Area of interest (AOI) drawn on the map | Planned |

Primary geospatial formats are GeoTIFF and TIFF. PNG and JPEG are retained for prescribed benchmark data where georeferencing is unavailable.

### 4.6 Sensor Awareness

- **Sentinel-2:** all thirteen bands (B1 to B12 and B8A) are recognised and native resolutions recorded. The model adapter decides which bands a checkpoint can consume.
- **Sentinel-1:** VV, VH or VV+VH is represented explicitly; SatQuery never assumes every SAR product has both.
- **Cartosat-2S and RISAT:** treated as domain-shift cases with sensor-specific metadata rather than as Sentinel data.

The prototype's validation module already identifies Sentinel-1, Sentinel-2, Cartosat and RISAT from file metadata, tags and product identifiers.

---

## 5. SOLUTION-TO-REQUIREMENT TRACEABILITY MATRIX

| Requirement ID | Problem Statement Requirement | SatQuery Component | Verification |
| :--- | :--- | :--- | :--- |
| REQ-01 | Natural-language queries | UI, Analysis Orchestrator, multilingual layer | Routing accuracy tests |
| REQ-02 | Single-image VQA | EarthMind-4B | RSVQA, VRSBench (base versus adapted) |
| REQ-03 | Captioning | EarthMind-4B | VRSBench captioning |
| REQ-04 | Visual grounding | EarthMind; GeoGround, Grounding DINO, SAM2 (optional) | VRSBench grounding |
| REQ-05 | Change detection and change VQA | Registration Quality Gate, MCD-Mamba, MCD-Mamba to EarthMind pipeline | IoU, F1; CDVQA |
| REQ-06 | Optical and SAR inputs | Sensor profiles, SAR tools, evidence-level fusion | Ablation; ISRO/SAC held-out set |
| REQ-07 | GeoTIFF support | Input validation, preprocessing, geo-processing | Integration tests |
| REQ-08 | Adapt at least one visual or VLM component | EarthMind adaptation on BigEarthNet.txt | Base versus adapted on held-out data |
| REQ-09 | Evidence-grounded, interpretable responses | Evidence Engine, claim verification, execution trace | Evidence Support Rate |
| REQ-10 | Usable interface | Web/GIS workspace | Task-based user testing |

---

## 6. SUCCESS CRITERIA

### 6.1 Quantitative

All values are measured by the team; literature values are reported separately.

| Area | Metric | Success Condition |
|---|---|---|
| VLM adaptation | RSVQA, VRSBench | Adapted EarthMind exceeds the measured base EarthMind on the same split |
| Change detection | IoU, F1, precision, recall | Reported for the exact checkpoint and configuration |
| Change VQA | CDVQA accuracy | MCD-Mamba to EarthMind pipeline exceeds EarthMind without change evidence |
| Evidence integrity | Evidence Support Rate | All numerical and geospatial claims supported |
| Orchestration | Capability-routing and plan accuracy | Measured on a curated query set |
| Multilingual | Answer agreement across languages | Same evidence and figures as the English answer |
| Latency | Metadata validation; deterministic tools | Under 3 s and under 5 s on benchmark-sized inputs; model latency reported as measured |

### 6.2 Qualitative

Auditability, usability for non-GIS users, extensibility through the registry contract, and visible uncertainty.

---

## 7. MVP AND SAFE FAILURE

### 7.1 MVP

| Must Work | Optional / Experimental / Future |
|---|---|
| Validation, EarthMind VQA, deterministic tools, Registration Quality Gate, MCD-Mamba, Evidence Engine, geospatial output, change VQA, execution trace | GeoGround, Grounding DINO, SAM2, TACMT / SAR grounding, DoFA, RSUniVLM, learned fusion, external data connectors, multilingual layer, production monitoring, multi-temporal series |

### 7.2 Safe Failure

Missing T2, missing required bands, poor registration, unsupported sensor, insufficient resolution or insufficient evidence produce a warning, a request for data, a partial answer or an explicit failure, never a fabricated answer.

---

## 8. ASSUMPTIONS AND CONSTRAINTS

- EarthMind receives RGB views of multispectral and SAR imagery through its adapter (true colour B04/B03/B02; SAR composite VV, VH, VV minus VH); this conversion is disclosed.
- MCD-Mamba must be served with its exact training configuration (mode, band count, patch size).
- The local 4 GB development GPU is not a target for EarthMind training or concurrent specialist execution.
- SatQuery reduces unsupported claims and exposes uncertainty; it cannot guarantee perfect model behaviour.

---

## 9. GLOSSARY

| Term | Definition |
|---|---|
| AI Analyst | EarthMind acting on validated evidence to produce the final explanation |
| Capability registry | Catalogue of models and tools with their capabilities, input requirements and evaluation status |
| EvidenceRecord | Structured record of one analytical result with provenance and parent links |
| Evidence Support Rate | Supported factual claims divided by factual claims made |
| Registration Quality Gate | Measured alignment check that blocks misregistered pairs |
| Safe failure | Qualified answer, request for data or explicit failure instead of an unsupported answer |
| VQA, VLM | Visual Question Answering; Vision-Language Model |

---
*End of Document*
