# Non-Functional Requirements Specification

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-004 |
| **Document Title** | Non-Functional Requirements Specification |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

Latency is measured by workflow and hardware. Planning targets are never presented as achieved results.

## 2. PERFORMANCE REQUIREMENTS

| ID | Requirement | Target | Verification | Prototype Status |
| :--- | :--- | :--- | :--- | :--- |
| NFR-PER-001 | Metadata validation | Under 3 s for normal benchmark files | Timed runs (raster inspection measured at 0.65 s for a 105-megapixel image) | Implemented |
| NFR-PER-002 | Deterministic calculations | Under 5 s for benchmark-sized tiles | Timed runs | Planned |
| NFR-PER-003 | VQA and change workflows | Measured latency reported by model, tile size and GPU | Latency table (`09_evaluation_strategy.md`) | Planned |
| NFR-PER-004 | Large scenes | Tiled processing without exhausting GPU memory | Stress tests with peak memory recorded | In Progress |
| NFR-PER-005 | Translation overhead | Translation adds a measured, reported latency per language | Timed runs | Planned |
| NFR-PER-006 | External data retrieval | Connector calls time-limited and cached by AOI and time window | Timed runs | Planned |

## 3. SCALABILITY REQUIREMENTS

| ID | Requirement | Target | Prototype Status |
| :--- | :--- | :--- | :--- |
| NFR-SCA-001 | MVP execution | Sequential model and tool execution without the production stack | In Progress |
| NFR-SCA-002 | Scale-out | Redis / Celery, PostGIS, object storage and multiple GPU workers added without changing the workflow contract | Planned |
| NFR-SCA-003 | Model services | Model services scaled or relocated by configuration only | In Progress |

## 4. RELIABILITY REQUIREMENTS

| ID | Requirement | Target | Prototype Status |
| :--- | :--- | :--- | :--- |
| NFR-REL-001 | Unsupported model/input combinations | Rejected before execution | Implemented (input validation); In Progress (model adapters) |
| NFR-REL-002 | Pair analysis | Requires registration validation | Implemented (compatibility checks); Planned (residual gate) |
| NFR-REL-003 | Failure handling | Retry, compatible fallback, partial answer or explicit failure | In Progress |
| NFR-REL-004 | Traceability | Every run produces an operational trace | In Progress |
| NFR-REL-005 | External sources | Connector failure degrades to analysis without that source, stated in the answer | Planned |

## 5. EVIDENCE INTEGRITY REQUIREMENTS

| ID | Requirement | Target | Prototype Status |
| :--- | :--- | :--- | :--- |
| NFR-EVD-001 | Every number has a source EvidenceRecord | All numerical claims | Planned |
| NFR-EVD-002 | Every EvidenceRecord stores parameters and tool/model version | All records | Planned |
| NFR-EVD-003 | Derived evidence references parent evidence | All derived records | Planned |
| NFR-EVD-004 | Final numerical and geospatial claims checked against evidence | All answers | Planned |
| NFR-EVD-005 | Conflicting evidence exposed as uncertainty | All conflicts | Planned |
| NFR-EVD-006 | Translation preserves verified figures, units and identifiers | All translated answers | Planned |
| NFR-EVD-007 | Answers, confidence values and evidence originate only from model and tool outputs | All answers | Implemented (orchestrator rule) |

## 6. SECURITY REQUIREMENTS

| ID | Requirement | Prototype Status |
| :--- | :--- | :--- |
| NFR-SEC-001 | Validate file structure (signature, type, readability, pixel limits) | Implemented |
| NFR-SEC-002 | Sanitise paths and inputs; typed identifiers | Implemented |
| NFR-SEC-003 | Allow-list tools; no dynamic code execution from queries | Implemented |
| NFR-SEC-004 | Bound parameters and resources | Implemented (validation limits) |
| NFR-SEC-005 | Authenticate protected deployments (JWT) and enforce roles | Planned |
| NFR-SEC-006 | Object-level authorisation (OLA / BOLA protection) | Planned |
| NFR-SEC-007 | Rate-limit expensive jobs | Planned |
| NFR-SEC-008 | Audit security-sensitive actions | Planned |
| NFR-SEC-009 | Server-side storage of model-service and connector credentials | In Progress |
| NFR-SEC-010 | Credential-safe logging | Implemented |

## 7. MAINTAINABILITY REQUIREMENTS

| ID | Requirement | Prototype Status |
| :--- | :--- | :--- |
| NFR-MNT-001 | All models and tools use the same adapter contract | Implemented (contract) |
| NFR-MNT-002 | Sensor profiles, languages and connectors are configuration-driven | Implemented (sensor patterns and workflows); Planned (languages, connectors) |
| NFR-MNT-003 | Core validator, registry, evidence and workflow paths covered by automated tests | Implemented (346 backend test functions) |

## 8. DEPLOYMENT AND PORTABILITY

| ID | Requirement | Prototype Status |
| :--- | :--- | :--- |
| NFR-DEP-001 | Core MVP does not require the complete production stack; Redis / Celery, MinIO, monitoring and reverse proxy are scaling extensions | Implemented |
| NFR-DEP-002 | Model hosts run locally, on campus or institutional GPUs, or in the cloud without changing the workflow contract | In Progress |
| NFR-DEP-003 | Model weights excluded from source control, images and database | Implemented |

## 9. USABILITY AND ACCESSIBILITY

| ID | Requirement | Prototype Status |
| :--- | :--- | :--- |
| NFR-USA-001 | GIS configuration hidden without hiding evidence | In Progress |
| NFR-USA-002 | Actionable error messages naming the failed check | Implemented |
| NFR-USA-003 | Interface and answers available in supported Indian languages | Planned |
| NFR-USA-004 | WCAG 2.1 AA for primary workflows | Planned |
