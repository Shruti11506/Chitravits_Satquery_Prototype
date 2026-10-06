# References and Research Basis

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-014 |
| **Document Title** | References and Research Basis |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Team** | Chitravits |
| **Version** | 4.0.0 |
| **Date** | 6 October 2026 |

## 2. CORE MODELS

**EarthMind** - Yan Shu et al., *EarthMind: Towards Multi-Granular and Multi-Sensor Earth Observation with Large Multimodal Models*, arXiv:2506.01667. https://arxiv.org/abs/2506.01667

**MCD-Mamba** - Mira Kenzhebay and Reza Arghandeh, *MCD-Mamba: Mamba-based framework for infrastructure change detection using multimodal satellite data*. https://github.com/Ci2Lab/MCD-Mamba ; https://doi.org/10.1080/01431161.2026.2665974

**GeoGround** - Yue Zhou et al., *GeoGround: A Unified Large Vision-Language Model for Remote Sensing Visual Grounding*, arXiv:2411.11904. https://arxiv.org/abs/2411.11904

## 3. OPTIONAL AND EXPERIMENTAL MODELS

Grounding DINO, SAM2, TACMT, DoFA and RSUniVLM are candidate external models. Full citations will be added from their official releases when they are admitted through the evaluation harness.

## 4. DATASETS

**BigEarthNet.txt** - Johann-Ludwig Herzog et al., *BigEarthNet.txt: A Large-Scale Multi-Sensor Image-Text Dataset and Benchmark for Earth Observation*, arXiv:2603.29630. https://arxiv.org/abs/2603.29630 ; official project page: https://txt.bigearth.net/

**Benchmarks** - VRSBench, RSVQA, CDVQA and OSCD are used according to the exact splits and protocols supported by the selected implementation.

## 5. EXTERNAL DATA SOURCES

Microsoft Planetary Computer (STAC), Copernicus CDSE, NASA Earthdata, ISRO Bhuvan, CAMS, IMD, NASA FIRMS, NASA EONET, USGS, NOAA / NCEI, NASA GIBS, AISStream, OpenStreetMap / Overpass and Copernicus Marine. Terms of use are recorded per source.

## 6. MULTILINGUAL RESOURCES

Candidate Indian-language translation options: open-source Indic translation models (for example, IndicTrans2) and the Government of India Bhashini platform. Selection follows the multilingual evaluation in `09_evaluation_strategy.md` Section 4.4.

## 7. SOFTWARE AND IMPLEMENTATION REFERENCE

FastAPI, LangGraph, Rasterio, GDAL, GeoPandas, Shapely, PyProj, PyTorch, Hugging Face Transformers, PEFT, React, PostgreSQL / PostGIS, Docker.

Prototype code base: https://github.com/Shruti11506/Chitravits_Satquery_Prototype

## 8. DOCUMENTATION RULE

Never copy published benchmark numbers into SatQuery results. Label literature values as literature baselines and report SatQuery measurements separately.
