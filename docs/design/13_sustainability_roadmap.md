# Sustainability and Future Roadmap

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-013 |
| **Document Title** | Sustainability and Future Roadmap |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Organization** | Indian Space Research Organisation (ISRO), Department of Space |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

---

## 2. SUSTAINABILITY STRATEGY

### 2.1 Maintainability
New specialists implement a stable interface for capabilities, input requirements, output schema, resources, execution and evidence generation. External models are added as model services and enabled through the evaluation harness, without changing the orchestration.

### 2.2 Deployment
Primary strategy: institutional or on-premise GPU where available, Dockerised services, PostgreSQL / PostGIS and optional S3-compatible storage. Cloud deployment remains possible. The current prototype runs on free-tier hosting with model services on a GPU host.

### 2.3 Model Sustainability
Version models independently and store the model or tool version in every EvidenceRecord.

### 2.4 Data Sustainability
Record dataset version, split, preprocessing configuration, checkpoint and evaluation-script version. Record source, licence and retrieval time for all external data.

### 2.5 Accuracy Sustainability
The evaluation harness re-runs benchmarks whenever a model, prompt or tool changes, and the capability registry is updated only on measured improvement (`09_evaluation_strategy.md` Section 6).

---

## 3. FUTURE ROADMAP

### 3.1 Short Term
- Stronger Cartosat / RISAT adapters.
- Grounding evaluation (GeoGround, Grounding DINO, SAM2).
- Additional SAR tools.
- Uncertainty calibration.
- Multi-date reasoning.
- Multilingual queries in English and Hindi.

### 3.2 Medium Term
- External data connectors (STAC, Copernicus CDSE, NASA Earthdata, ISRO Bhuvan, IMD, FIRMS, EONET and others).
- Scheduled monitoring.
- Temporal series.
- Multilingual queries in further Indian languages, including speech input.
- More satellite profiles.
- Experimental specialists (TACMT, DoFA, RSUniVLM) evaluated for admission.

### 3.3 Long Term
- Cross-satellite consensus.
- Persistent Earth monitoring.
- Sensor-specific adaptation.
- Operational decision-support integration.

InSAR, hyperspectral analysis and orbital or edge deployment remain future research directions rather than MVP requirements.

---

## 4. SCALABILITY PLAN

| Stage | Approach |
|---|---|
| Prototype | Modular monolith; sequential execution; local or object storage |
| Scale-out | Redis / Celery, PostgreSQL / PostGIS, MinIO or S3-compatible storage, multiple GPU workers |
| Connectors | Caching by AOI and time window; rate-limit aware clients |
| Multilingual | Translation service scaled independently of model services |

---

## 5. IMPACT ASSESSMENT

| Beneficiary | Impact |
|---|---|
| ISRO and SAC analysts | Faster, auditable analysis with provenance |
| NDRF and State Disaster Management Authorities | Rapid change and flood assessment, supported by external hazard data, in local languages |
| Agricultural and district officers | Vegetation and land-use change analysis without GIS training |
| Researchers and students | Reproducible evidence-based workflows |

Alignment: National Geospatial Policy 2022, Digital India, disaster management and Smart Cities programmes; SDG 2, 6, 11, 13 and 15.

---

## 6. PARTNERSHIP OPPORTUNITIES

Opportunities only; no approval is implied.
- ISRO / SAC: Cartosat and RISAT product guidance and held-out validation.
- NRSC and Bhuvan: operational hosting and data access.
- Language platforms (for example, Bhashini): Indian-language translation services.
- Academic institutions: GPU access and evaluation collaboration.

---

## 7. LICENSING

SatQuery integration code is openly documented subject to the licences of incorporated models, datasets, translation services and external data sources. Third-party weights and data are not redistributed unless permitted.
