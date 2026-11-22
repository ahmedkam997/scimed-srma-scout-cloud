# SciMed SRMA Scout Cloud Architecture

## Purpose

SciMed SRMA Scout Cloud is a mobile-first, publication-oriented discovery and verification system for systematic review and meta-analysis topics across study designs.

## Core design

The system separates deterministic research safeguards from AI-assisted interpretation.

- Deterministic engine: source states, study-family counts, synthesis usability, locked gates, Type-A blocking logic, audit logs.
- AI layer: candidate generation, PICO refinement, semantic overlap interpretation, clinical rationale, editorial stress testing.
- External evidence layer: PubMed, Europe PMC, OpenAlex, Crossref, ClinicalTrials.gov, PROSPERO, OSF and additional registries when relevant.
- Persistence layer: project checkpoints, source logs, candidate ledger and final review packages.
- Final review layer: independent ChatGPT Plus review of the exported evidence package.

## Fail-closed source rule

A source failure must never be converted into a negative search result. Supported states are:

- SEARCHED_NEGATIVE
- SEARCHED_POSITIVE
- PARTIAL
- ACCESS_FAILED
- NOT_SEARCHED
- MANUAL_VERIFIED

## Locked final-review option requirements

Each fully qualified final-review option must pass all locked gates, including at least four verified independent eligible studies, at least four verified synthesis-usable studies, no unresolved Type-A issue, adequate novelty, clinical importance, publication potential and editorial stress-test performance. The engine exports several qualified or clearly labeled provisional options. It does not select the overall winner. ChatGPT performs the independent final comparison.
