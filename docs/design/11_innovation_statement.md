# Innovation and Novelty Statement

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-011 |
| **Document Title** | Innovation and Novelty Statement |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

## 2. CORE THESIS

SatQuery is not novel because it uses EarthMind, MCD-Mamba or GeoGround. These are existing research systems.

The proposed contribution is the **evidence-grounded orchestration layer that turns heterogeneous remote sensing models and deterministic tools into one auditable query system**.

## 3. NOVELTY DIMENSIONS

### 3.1 Capability-Aware Query Planning
`query -> required capabilities -> evidence requirements -> workflow -> tools/models`

### 3.2 Evidence Engine
Every model or tool output becomes an EvidenceRecord containing provenance, spatial footprint, parameters, uncertainty and parent evidence.

### 3.3 Evidence-Backed VLM Reasoning
EarthMind may interpret imagery, but quantitative and geospatial claims are grounded in explicit evidence and verified before presentation.

### 3.4 Specialist-to-Analyst Pipeline (MCD-Mamba to EarthMind)
A change specialist determines where change occurred; deterministic tools supply spectral attribution; the VLM explains only the validated evidence. This separates detection, measurement and interpretation, each with its own provenance.

### 3.5 Cross-Modal Evidence Fusion
Optical and SAR are analysed independently, aligned spatially and compared. Agreement strengthens support; disagreement becomes visible uncertainty.

### 3.6 Evaluation-Gated Model Integration
External models join through a common contract and are enabled for a capability only after the evaluation harness accepts them, so the registry reflects measured performance rather than assumed performance.

### 3.7 Evidence-Preserving Multilingual Answers
Queries in Indian languages are translated for analysis, and answers are translated only after claim verification, with figures, units and evidence identifiers preserved exactly.

### 3.8 Safe Failure
Missing bands, missing modalities, poor registration, insufficient resolution and insufficient evidence trigger qualified failure rather than confident guessing.

## 4. COMPARISON

| Feature | SatQuery AI | Single RS VLM | Scripted GIS Platform |
|---|---|---|---|
| Natural-language queries (including Indian languages) | Yes (multilingual planned) | Usually English only | No |
| Capability-aware planning | Yes | No | Manual |
| Deterministic measurements | Yes | No | Yes |
| Evidence provenance and claim verification | Yes | No | Script history only |
| Optical-SAR disagreement exposed | Yes | Rarely | Manual |
| Evaluation-gated model registry | Yes | Not applicable | Not applicable |
| Safe failure | Yes | Rarely | Errors only |

The SatQuery column describes the design; implementation status is given in `01_solution_overview.md` Section 4.1.

## 5. WHAT IS NOT CLAIMED AS NOVEL

EarthMind, MCD-Mamba, GeoGround, Grounding DINO, SAM2, spectral-index mathematics, GDAL / Rasterio, LangGraph, translation models and external data services are existing components.

Potential intellectual property areas are prior-art-search hypotheses, not guaranteed patent claims:
- capability-to-evidence workflow planning;
- evidence provenance graph for EO model and tool outputs;
- evidence-level optical / SAR uncertainty fusion;
- quantitative and geospatial claim verification for VLM outputs;
- evidence-preserving translation of verified analytical answers.
