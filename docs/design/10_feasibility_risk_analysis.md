# Feasibility and Risk Analysis

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-010 |
| **Document Title** | Feasibility and Risk Analysis |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

## 2. TECHNICAL FEASIBILITY

SatQuery is feasible as a staged prototype if it prioritises deterministic tools, one primary VLM, one change specialist, evidence infrastructure and a narrow demonstration. Optional models, external connectors and multilingual support are added through the same contracts without changing the core.

The prototype already provides the application foundation: upload, raster metadata and previews, sensor-aware input validation, pair compatibility checks, persistent sessions and results, PDF reporting, a LangGraph orchestrator and the model service contract. EarthMind and MCD-Mamba model services and the agent integration are under integration.

### 2.1 Compute Strategy
Use sequential model loading, quantisation where compatible, tiling and cached preprocessing. Do not assume all models remain resident in GPU memory. The local 4 GB development GPU is not a target for EarthMind training or concurrent specialist execution; institutional or cloud GPUs are used for heavier experiments. EarthMind requires approximately 9 GB per variant at FP16; MCD-Mamba requires Linux or WSL2 with CUDA.

### 2.2 Model and Data Availability
EarthMind, GeoGround, Grounding DINO and SAM2 have public weights; MCD-Mamba requires training by the team. BigEarthNet.txt, VRSBench, RSVQA, CDVQA and OSCD are public research datasets; most external connectors are public services with registration or usage terms.

### 2.3 Multilingual Feasibility
Translation runs as a separate step before planning and after verification, so it does not affect model or tool behaviour. Open-source Indic translation models or the Bhashini platform can be integrated as a service; initial scope is English and Hindi.

## 3. ECONOMIC FEASIBILITY
Free tiers for interface, API and database; GPU through institutional hardware, the team workstation or serverless GPU credits. No paid language-model APIs are required.

## 4. OPERATIONAL FEASIBILITY
Prototype as a modular monolith. Add Celery / Redis, object storage, PostGIS and multiple GPU workers only when workload requires them. Containerised services allow deployment on institutional infrastructure.

## 5. RISK REGISTER

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R01 | GPU out of memory | Medium | High | Quantisation, tiling, sequential loading |
| R02 | Model latency | High | High | Caching, small tiles, asynchronous execution |
| R03 | EarthMind domain shift | High | High | Adaptation and deterministic evidence |
| R04 | Cartosat / RISAT shift | High | High | Sensor profiles and held-out testing |
| R05 | Registration error | Medium | High | Registration Quality Gate |
| R06 | SAR mismatch | Medium | High | Preserve polarization and product metadata; reject pairs with differing polarizations |
| R07 | Agent routing error | Medium | High | Capability registry and deterministic fallback |
| R08 | Hallucination | High | High | Evidence Engine and claim verification |
| R09 | Tiny targets | Medium | High | GSD feasibility gate |
| R10 | Dataset processing time | High | Medium | Subset first |
| R11 | Scope creep | High | High | Explicit MVP and future boundary |
| R12 | MCD-Mamba configuration mismatch | Medium | High | Serve with recorded training configuration; verify masks on OSCD test pairs |
| R13 | Translation alters meaning or figures | Medium | High | Protected spans; translation after verification; figures copied verbatim; EO glossary |
| R14 | Unsupported language or dialect | Medium | Medium | Clear fallback to English; staged language rollout |
| R15 | External connector outage or licence restriction | Medium | Medium | Caching; graceful degradation; licence recorded per source |
| R16 | External model underperforms or is incompatible | Medium | Medium | Evaluation-harness gating before enablement |
| R17 | Unauthorised access without authentication | High | High | JWT, RBAC, object-level authorisation, rate limiting before public release |
| R18 | Optical-SAR pairs rejected by the change-detection pair check (prototype) | High | High | Pair-type selection routing optical-SAR pairs to the optical-SAR workflow |

## 6. RISK HEATMAP

| Probability / Impact | Medium | High |
| :--- | :--- | :--- |
| **High** | R10 | R02, R03, R04, R08, R11, R17, R18 |
| **Medium** | R14, R15, R16 | R01, R05, R06, R07, R09, R12, R13 |

## 7. FALLBACK POLICY

Fallbacks must solve the same capability:

| Capability | Fallback |
|---|---|
| Water detection | MNDWI / SAR-Otsu |
| Vegetation loss | NDVI temporal analysis |
| Change detection | Compatible change detector |
| VQA | Alternate VLM or qualified failure |
| Grounding | Alternate grounding provider or qualified failure |
| Translation | Verified English answer with notice |
| External data | Analysis without the source, stated in the answer |

An unrelated index is not a valid generic fallback.

## 8. SCOPE CONTINGENCY

If adaptation fails, the system can still demonstrate:

`EarthMind base + deterministic tools + MCD-Mamba + Evidence Engine`

If multilingual support or external connectors are not ready, the English pipeline is demonstrated without them. The system-level architecture does not depend on training a new foundation model.

## 9. SWOT ANALYSIS

| Strengths | Weaknesses |
|---|---|
| Evidence-grounded design; validated inputs; tested application foundation; modular registry for new models | Model processing under integration; EarthMind uses RGB views of multispectral and SAR data; deterministic tools and claim verification still to be built |

| Opportunities | Threats |
|---|---|
| Multilingual access for field users; external data for disaster response; institutional deployment | Domain shift to Indian scenes and sensors; GPU availability; dependence on third-party services and licences |
