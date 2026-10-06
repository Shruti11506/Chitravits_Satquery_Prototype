# Project Timeline and Resource Plan

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-012 |
| **Document Title** | Project Timeline and Resource Plan |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

## 2. MVP-FIRST PLAN

| Week | Work Items | Prototype Status |
|---|---|---|
| 1 | Architecture freeze; model roles; evidence schema; tool contract; sensor profiles | Implemented (contract, orchestrator, sensor identification); evidence schema extension Planned |
| 2 | GeoTIFF ingestion; Sentinel-1/2 profiles; Cartosat / RISAT metadata; tiling; registration gate | Implemented (ingestion, profiles, pair checks); registration residual gate Planned |
| 3 | NDVI, NDWI / MNDWI, NDBI; SAR dB / VV / VH / RVI / Otsu; temporal difference / MAD; area calculation; evidence persistence | Evidence persistence Implemented; tools Planned |
| 4 | EarthMind adapter; MCD-Mamba adapter; optional GeoGround adapter | In Progress |
| 5 | Capability registry; query routing; workflow planner; session state; failure handling; evidence verification; MCD-Mamba to EarthMind pipeline | Routing and session state Implemented; agent pipeline In Progress; verification Planned |
| 6 | Chat, GIS map, metadata / validation, before / after slider, evidence panel and execution trace; language selector | Chat and validation panel Implemented; others Planned |
| 7 | Benchmark runs, ablations, routing tests, evidence-support tests, failure tests; accuracy improvement iterations; multilingual evaluation | Planned |
| 8 | Cartosat / RISAT held-out evaluation, domain-shift analysis, latency measurement and stabilisation; first external model admitted through the evaluation harness | Planned |
| 9 | Documentation, presentation, reproducible deployment, fallback demonstration and final regression | Deployment configuration Implemented; remainder Planned |

## 3. EXTENSION TRACK (AFTER MVP ITEMS ARE STABLE)

| Item | Dependency |
|---|---|
| Multilingual queries (English and Hindi first) | Claim verification, so translation follows verified answers |
| External model integration (GeoGround, Grounding DINO, SAM2) | Evaluation harness |
| External data connectors (STAC, Copernicus, FIRMS, IMD, Bhuvan) | AOI support and external evidence records |
| Security gateway (JWT, RBAC, rate limiting, audit) | Required before public release |

## 4. TEAM ROLES

Team Chitravits: three full-stack developers, two AI/ML members and one cybersecurity member; the Agent and Orchestration specialist (M4) leads AI integration.

| Workstream | Lead | Support |
|---|---|---|
| Model adapters, adaptation, accuracy programme | AI/ML | M4 |
| Orchestration, evidence engine, MCD-Mamba to EarthMind pipeline | M4 | AI/ML |
| Interface, GIS viewer, multilingual interface | Full-stack | M4 |
| Deterministic tools and geo-processing | AI/ML | Full-stack |
| External models and connectors | M4 | Full-stack |
| Security gateway | Cybersecurity | Full-stack |
| Evaluation harness | AI/ML | M4 |

## 5. MILESTONES

| Milestone | Deliverable | Status |
|---|---|---|
| M1 | Validated ingestion and session persistence | Implemented |
| M2 | Model contract and orchestrator | Implemented |
| M3 | EarthMind and MCD-Mamba answers in the workspace | In Progress |
| M4 | Deterministic tools and Evidence Engine with verification | Planned |
| M5 | MCD-Mamba to EarthMind change VQA | Planned |
| M6 | Measured benchmark, ablation and held-out results | Planned |
| M7 | Multilingual queries, first external model, security gateway | Planned |

## 6. CRITICAL PATH

`validation -> preprocessing -> adapters -> Evidence Engine -> orchestration -> UI -> evaluation`

The Evidence Engine should be implemented early because every specialist, the MCD-Mamba to EarthMind pipeline and multilingual output depend on its contract.

## 7. CUT-FIRST RULE

If time is constrained, cut external connectors, advanced learned fusion, optional grounding, additional languages beyond Hindi, production monitoring and advanced asynchronous infrastructure before cutting validation, evidence, registration, core VQA, change detection or deterministic tools.

## 8. RESOURCE REQUIREMENTS

| Resource | Requirement |
|---|---|
| Development | Team computers including a 4 GB GPU (development only) |
| GPU | Institutional or campus GPU (RTX A6000 requested), team workstation, or serverless GPU |
| Storage | BigEarthNet.txt subsets (full imagery approximately 100 GB compressed) |
| Software | Open source; model, dataset and connector licences reviewed |
| Hosting | Free tiers for interface, API and database |
