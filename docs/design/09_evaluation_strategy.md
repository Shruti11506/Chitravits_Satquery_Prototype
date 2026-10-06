# Evaluation and Testing Strategy

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-009 |
| **Document Title** | Evaluation and Testing Strategy |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Organization** | Indian Space Research Organisation (ISRO), Department of Space |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

**Rules:** do not copy paper scores as SatQuery results; report every result with checkpoint, dataset split, preprocessing and hardware; never tune on ISRO/SAC hidden annotations.

---

## 2. EVALUATION LEVELS

1. Deterministic tools.
2. Specialist models.
3. Workflow and orchestration.
4. End-to-end evidence-grounded answers.

The Evaluation Harness (architecture Block 17) runs these levels automatically, compares models and tools, generates evaluation reports and updates the capability registry.

---

## 3. MODEL EVALUATION

### 3.1 EarthMind
Evaluate single-image VQA, captioning and supported multimodal reasoning on RSVQA and VRSBench. Compare base and adapted checkpoints.

### 3.2 MCD-Mamba
Report IoU, F1, precision and recall for the exact checkpoint, dataset and configuration (OSCD). The published MCD-Mamba work is multimodal optical / SAR change detection; its numbers are literature baselines, not SatQuery measurements.

### 3.3 MCD-Mamba to EarthMind Pipeline
Evaluate change VQA on CDVQA in three configurations: EarthMind on T1/T2 only; EarthMind with the MCD-Mamba change summary; EarthMind with change summary and spectral attribution evidence. Report per question type, together with the Evidence Support Rate of the explanations.

### 3.4 Grounding Models
If enabled, evaluate the exact grounding output used (HBB, OBB and/or mask) for GeoGround, Grounding DINO and SAM2.

### 3.5 External Models
Every external model is evaluated on the benchmark for each capability it declares before the harness enables it.

---

## 4. TOOL, REGISTRATION AND ORCHESTRATION EVALUATION

### 4.1 Deterministic Tools
Reference and synthetic cases verify formulas, band mappings, NoData handling, thresholds and area calculations.

### 4.2 Registration Quality Gate
Controlled spatial offsets measure false acceptance, false rejection and residual stability.

### 4.3 Agent Evaluation
Capability-routing accuracy, workflow-plan accuracy, tool-parameter correctness, unnecessary-tool rate, failure recovery and trace completeness.

### 4.4 Multilingual Evaluation

| Metric | Definition |
|---|---|
| Routing agreement | Share of translated queries routed to the same capabilities as their English reference |
| Answer consistency | Share of translated answers whose figures, units and evidence identifiers match the verified English answer exactly |
| Translation quality | Human review of EO terminology on a sample; automatic metrics where references exist |
| Latency overhead | Additional time per query for translation |

---

## 5. EVIDENCE EVALUATION

For every answer:
- Is every number supported?
- Is every geometry supported?
- Is the correct asset used?
- Are parameters and version recorded?
- Is parent evidence preserved?
- Does the answer contradict evidence?

`Evidence Support Rate = supported factual claims / factual claims made`

---

## 6. ACCURACY IMPROVEMENT PROGRAMME

Accuracy is improved systematically, and every change is accepted only if it improves measured results on held-out data.

| No. | Lever | Method | Measured By |
|---|---|---|---|
| 1 | Domain adaptation | Parameter-efficient adaptation (LoRA / adapters) of EarthMind on BigEarthNet.txt, with geographically stratified splits | Base versus adapted on RSVQA, VRSBench and BigEarthNet.txt held-out sets |
| 2 | Measurement by tools | Quantities (areas, indices, counts from masks) produced by deterministic tools, not by VLM text | Evidence Support Rate; numerical error against reference |
| 3 | Change evidence for change VQA | MCD-Mamba mask and spectral attribution supplied to EarthMind as context | CDVQA accuracy with and without evidence |
| 4 | Input quality gates | Registration Quality Gate, GSD feasibility, cloud masking and band checks remove inputs that cause wrong answers | Error rate on reliability tests |
| 5 | Input conversion choice | Compare true colour, false colour and SAR composites for EarthMind | VQA accuracy per conversion |
| 6 | Prompt templates | Task-specific prompts tuned on a validation split, then frozen | Validation and test accuracy |
| 7 | Cross-evidence checking | Optical and SAR evidence compared; agreement raises support, disagreement lowers confidence | Accuracy of answers marked high-confidence |
| 8 | Specialist selection | Evaluation harness enables the best provider per capability (for example, GeoGround or SAM2 for grounding) | Per-capability benchmark |
| 9 | Post-processing | Thresholds, morphological filtering and minimum-area filtering of change masks tuned on validation data | IoU, F1 |
| 10 | Test-time tiling and overlap | Overlapping tiles with merge rules for large scenes | IoU at tile borders |
| 11 | Confidence calibration | Calibrate model scores where available; qualify low-confidence answers | Calibration error |
| 12 | Error analysis loop | Failed cases from evaluation and user feedback categorised and used for targeted data and prompt changes | Error category counts over time |

Literature results are used only as reference points. An improvement is reported only after it is measured on the same split as the baseline.

---

## 7. OPTICAL-SAR AND HELD-OUT EVALUATION

### 7.1 Optical-SAR
Compare optical-only, SAR-only, independent-evidence fusion and any learned fusion. Claim improvement only if the ablation demonstrates it.

### 7.2 ISRO/SAC
Treat Cartosat-2S and RISAT as held-out evaluation. Record sensor, GSD, preprocessing, task, result and failure mode.

---

## 8. RELIABILITY TESTS

Wrong modality, missing band, clouds, SAR noise, tiny targets, registration failure, corrupted file, unsupported sensor, ambiguous query, unsupported language, unavailable external source and insufficient evidence must be handled without confident fabrication.

---

## 9. SOFTWARE TESTING (IMPLEMENTATION REFERENCE)

The prototype backend contains 346 automated test functions in 28 files, using an in-memory database substitute. They cover file, sensor, modality, band, workflow and pair validation (186 functions), imagery upload, pairs and previews (58), conversations, analysis and results (37), the LangGraph orchestrator (15), profile, settings, projects and reports (30) and infrastructure (20). Model evaluation, multilingual evaluation and continuous integration are planned additions.

---

## 10. RESULTS TEMPLATES

### 10.1 Benchmark Results

| Benchmark | Metric | Model / Configuration | Base | Adapted / Pipeline | Literature Baseline | Date |
|---|---|---|---|---|---|---|
| RSVQA-LR / HR | Overall and average accuracy | EarthMind-4B | | | | |
| VRSBench | Captioning, grounding, VQA | EarthMind-4B; grounding providers | | | | |
| CDVQA | Accuracy | EarthMind alone / with change evidence / with attribution | | | | |
| OSCD | IoU, F1, precision, recall | MCD-Mamba | | Not applicable | | |
| BigEarthNet.txt held-out | Task metric | EarthMind-4B | | | | |

### 10.2 System Results

| Metric | Target | Measured | Date |
|---|---|---|---|
| Capability-routing accuracy | Set after first measurement | | |
| Evidence Support Rate | All numerical claims supported | | |
| Multilingual routing agreement | Set after first measurement | | |
| Multilingual answer consistency | All figures identical | | |
| Metadata validation latency | Under 3 s | | |
| Deterministic tool latency | Under 5 s | | |

### 10.3 ISRO/SAC Held-Out

| Sensor | GSD | Preprocessing | Task | Result | Failure Mode |
|---|---|---|---|---|---|
| Cartosat-2S | | | | | |
| RISAT | | | | | |
| Cartosat-2S + RISAT | | | | | |

---
*End of Document*
