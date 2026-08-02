# Automation-First Roadmap for a Trade Marks Examination Knowledge System

## Purpose

The Trade Marks Examination Manual contains interconnected legal concepts, examination practices, legislation, case law, evidence requirements, exceptions, procedures and examples.

The project’s purpose is to transform that material from a collection of documents into a structured knowledge system that supports:

1. **Search** — helping users find relevant information even when they do not use the manual’s exact terminology.
2. **AI retrieval** — supplying AI systems with the most relevant passages, concepts, authorities and related material before they generate an answer.
3. **Automated reasoning** — enabling carefully defined classification, dependency analysis, consistency checking and limited inference over approved knowledge.

This retains the original roadmap’s intention to represent the knowledge, reasoning and concepts used in trade mark examination, rather than merely reproducing the manual’s pages and headings.

The project should be **automation-first but human-governed**. Natural language processing, machine learning and large language models should perform most of the repetitive work. Human experts should concentrate on:

* defining the project boundaries;
* resolving ambiguity;
* approving important legal concepts and relationships;
* validating rules and exceptions;
* reviewing uncertain or high-risk outputs;
* monitoring overall quality.

---

# 1. What the system will contain

The completed system will consist of several connected components.

| Component                    | Purpose                                                                       |
| ---------------------------- | ----------------------------------------------------------------------------- |
| Source repository            | Stores the original manual, legislation, cases and related material           |
| Document processing pipeline | Converts documents into clean, structured and traceable text                  |
| Controlled vocabulary        | Records preferred terms, synonyms and broader or narrower concepts            |
| Ontology                     | Defines what kinds of things exist and how they may relate                    |
| Knowledge graph              | Contains the actual provisions, cases, concepts, paragraphs and relationships |
| Search index                 | Supports fast keyword, semantic and filtered search                           |
| Validation layer             | Detects missing, malformed or unsupported graph information                   |
| Reasoning layer              | Produces approved classifications, inferred relationships and impact warnings |
| AI retrieval service         | Selects and packages evidence for an AI assistant                             |
| Review interface             | Allows experts to inspect uncertain or legally significant machine output     |

The original documents remain the authoritative sources. The ontology and knowledge graph provide a structured and governed representation of those sources.

---

# 2. Guiding operating model

## Machines perform candidate generation

Automated processes should:

* parse and segment documents;
* extract keyphrases;
* recognise known entities;
* identify legislation and case citations;
* propose new concepts;
* group similar terminology;
* suggest concept hierarchies;
* extract candidate relationships;
* identify candidate requirements and exceptions;
* generate graph records;
* detect data-quality problems;
* rerun when source documents change.

## Humans manage exceptions and legal meaning

Experts should not manually catalogue every paragraph. Instead, they should review:

* new or ambiguous concepts;
* proposed synonyms with uncertain equivalence;
* important legal relationships;
* extracted exceptions;
* competing interpretations;
* candidate executable rules;
* low-confidence records;
* samples of automatically approved records.

## Confidence-based processing

Each machine-generated result should receive:

* an extraction method;
* a confidence score;
* an exact supporting passage;
* a proposed status;
* a risk category.

Suggested processing tiers are:

### Tier 1 — Deterministic

Examples:

* exact legislative citations;
* manual paragraph identifiers;
* dates;
* document versions;
* known case citations.

These can generally be accepted automatically after the extraction method has demonstrated very high accuracy.

### Tier 2 — Probabilistic but low risk

Examples:

* candidate keywords;
* document topics;
* suggested synonyms;
* likely concept classifications.

High-confidence results may be accepted automatically with sample-based auditing. Lower-confidence results enter a review queue.

### Tier 3 — Legally significant

Examples:

* a case overrides an earlier principle;
* an exception qualifies a general rule;
* evidence is required rather than merely relevant;
* an instruction creates an obligation;
* a legal conclusion follows from stated conditions.

These should require expert approval until the organisation has substantial evidence that a narrowly defined extraction process is reliable.

---

# 3. Recommended technology stack

The technologies below provide a practical reference implementation. Equivalent agency-approved products may be substituted.

| Function                           | Recommended technology                                            |
| ---------------------------------- | ----------------------------------------------------------------- |
| Main programming language          | Python                                                            |
| Document conversion                | Docling                                                           |
| General file-format fallback       | Apache Tika                                                       |
| Basic NLP                          | spaCy                                                             |
| Keyphrase extraction               | YAKE                                                              |
| Rule-based entity recognition      | spaCy EntityRuler, PhraseMatcher and regular expressions          |
| Linguistic relationship patterns   | spaCy DependencyMatcher                                           |
| Semantic similarity and clustering | Sentence Transformers                                             |
| Complex structured extraction      | An agency-approved LLM using schema-constrained JSON output       |
| Vocabulary standard                | SKOS                                                              |
| Ontology language                  | RDF, RDFS and OWL 2 RL                                            |
| Ontology editing                   | WebProtégé or Protégé Desktop                                     |
| Provenance model                   | PROV-O plus project-specific fields                               |
| Python graph processing            | RDFLib                                                            |
| Graph validation                   | SHACL using pySHACL                                               |
| Prototype graph server             | Apache Jena Fuseki                                                |
| Graph query language               | SPARQL                                                            |
| Search and vector retrieval        | OpenSearch                                                        |
| Pipeline scheduling                | Existing agency scheduler, Prefect, Airflow or GitHub Actions     |
| Pilot review interface             | Streamlit or a lightweight internal web application               |
| Automated testing                  | pytest, SPARQL regression queries and retrieval benchmark scripts |

Docling can convert source documents into a structured representation and supports workflows including chunking and RAG preparation. Apache Tika is a useful fallback for extracting text and metadata from many file formats.

---

# 4. End-to-end process

```text
Source documents
        ↓
Document parsing and segmentation
        ↓
Candidate terms, entities and citations
        ↓
Term consolidation and concept linking
        ↓
Relationship, proposition and rule extraction
        ↓
Automated confidence assessment
        ↓
Targeted expert review
        ↓
Controlled vocabulary and ontology
        ↓
Validated knowledge graph
        ↓
Search, AI retrieval and reasoning
        ↓
Evaluation and continuous reprocessing
```

The following stages explain how to implement this process.

---

# Stage 0 — Select the pilot and create the evaluation set

## Objective

Define a manageable first domain and establish how the system will be tested before building it.

## Recommended scope

Choose one examination area that:

* is important to examiners;
* appears across multiple manual sections;
* connects to legislation and case law;
* contains some relationships and exceptions;
* is sufficiently contained for a pilot.

Distinctiveness may be suitable, but the final selection should be based on operational need.

## Tasks

### Define competency questions

Competency questions are ordinary questions that the completed system must answer.

Examples:

* What guidance discusses acquired distinctiveness?
* Which provisions provide the legislative basis?
* What forms of evidence may be relevant?
* Which cases interpret the relevant test?
* What manual material cites a particular case?
* What guidance was current on a specified date?
* What material would be affected if a provision changed?
* What exact passage supports this AI-generated answer?

### Create a gold-standard test set

Experts manually prepare a relatively small set of trusted examples:

* 100–300 recognised entities;
* 50–100 approved concepts;
* 50–100 known relationships;
* 20–50 search questions;
* 20–50 AI retrieval questions;
* expected reasoning results;
* examples of conclusions the system must not make.

This is one of the most important uses of expert time. It allows every automated component to be measured objectively.

## Technology

* Spreadsheet or annotation tool for initial labelling;
* Python evaluation scripts;
* pytest for automated regression tests;
* Git for version control.

## Human role

Experts define the questions and approve the gold-standard answers. They do not process the entire manual.

## Deliverables

* pilot scope;
* competency-question catalogue;
* gold-standard dataset;
* prohibited-use list;
* evaluation measures.

---

# Stage 1 — Ingest and structure the source documents

## Objective

Convert the manual and related authorities into machine-processable text while preserving their structure and origin.

## Automated process

### Document conversion

Use **Docling** as the primary parser for PDFs and Office documents.

Extract:

* document title;
* version;
* headings;
* paragraphs;
* lists;
* tables;
* footnotes;
* page numbers;
* reading order;
* hyperlinks.

Use **Apache Tika** as a fallback for formats that Docling does not process adequately.

Use OCR only where the source is scanned or has no usable text layer.

### Stable segmentation

Divide each source into addressable units:

```text
Document
└── Version
    └── Chapter
        └── Section
            └── Paragraph
                └── Sentence
```

Every unit receives a stable identifier, for example:

```text
tmem:manual/2026-01/chapter-4/section-3/paragraph-12
```

### Source fingerprinting

Generate a checksum for each document and passage. This allows the pipeline to detect:

* new documents;
* amended passages;
* removed passages;
* unchanged content that does not require reprocessing.

## Human role

Review a sample of parsed documents and resolve recurring layout problems. Human review should focus on improving the parser rather than correcting every document manually.

## Deliverables

* structured source corpus;
* stable identifiers;
* version register;
* document metadata;
* change-detection process;
* source-quality report.

## Quality gate

The parser must reliably preserve:

* headings;
* paragraph boundaries;
* citations;
* page references;
* the link between extracted text and its original source.

---

# Stage 2 — Extract candidate terminology and entities

## Objective

Automatically identify important language and identifiable legal objects.

## 2.1 Keyphrase extraction

Use **YAKE** to identify important words and phrases within each section and chapter.

YAKE is a lightweight, unsupervised keyword-extraction method based on statistical characteristics of individual documents.

Likely outputs include:

* acquired distinctiveness;
* evidence of use;
* relevant date;
* ground of refusal;
* ordinary signification;
* honest concurrent use.

YAKE outputs should be treated as candidate terminology rather than approved ontology entities.

## 2.2 Known entity recognition

Use:

* regular expressions;
* spaCy `EntityRuler`;
* spaCy `PhraseMatcher`;
* authoritative lists.

Target entities include:

* legislative provisions;
* Act and regulation names;
* court and tribunal decisions;
* manual sections;
* application numbers;
* dates;
* courts;
* institutional roles;
* known legal concepts.

The spaCy EntityRuler can use exact phrase and token patterns and can operate alongside a statistical entity recogniser.

## 2.3 New entity discovery

Use a combination of:

* a custom spaCy named-entity recognition model;
* an agency-approved LLM;
* the surrounding sentence;
* existing vocabulary terms;
* section headings.

The LLM should return structured output such as:

```json
{
  "text": "evidence of use",
  "proposed_type": "EvidenceCategory",
  "source_sentence_id": "sentence-1842",
  "confidence": 0.91,
  "reason": "The phrase describes a category of evidence considered in examination."
}
```

The model should not be asked to generate free-form ontology content without evidence spans.

## 2.4 Citation resolution

Use rules and authoritative registers to convert references such as:

* “s 41”;
* “subsection 41(3)”;
* “the Cantarella decision”;

into stable identifiers for the actual provision or decision.

## Human role

Review:

* proposed new entity categories;
* unresolved citations;
* ambiguous abbreviations;
* samples of high-confidence automatic results;
* all legally significant entity-linking conflicts.

## Deliverables

* candidate-term register;
* recognised-entity register;
* citation links;
* confidence scores;
* unresolved-entity queue.

---

# Stage 3 — Consolidate terminology and build the controlled vocabulary

## Objective

Turn thousands of extracted phrases into a smaller governed set of concepts.

## Automated process

### Normalisation

Automatically normalise:

* capitalisation;
* punctuation;
* singular and plural forms;
* spelling variants;
* abbreviations;
* minor formatting differences.

### Semantic similarity

Use **Sentence Transformers** to generate embeddings for candidate terms, definitions and surrounding passages.

Sentence Transformers supports semantic similarity, semantic search, paraphrase mining and clustering using text embeddings.

Use cosine similarity and clustering to propose groups such as:

```text
Acquired distinctiveness
Distinctiveness acquired through use
Distinctiveness as a result of use
Factual distinctiveness
```

### Suggested clustering techniques

* agglomerative clustering for interpretable grouping;
* HDBSCAN where the number of clusters is unknown;
* nearest-neighbour similarity for reviewing individual terms;
* cross-encoder reranking for difficult synonym decisions.

### LLM-assisted concept comparison

For each proposed pair or cluster, ask the LLM to classify it as:

* exact synonym;
* alternative label;
* broader concept;
* narrower concept;
* closely related concept;
* unrelated;
* uncertain.

Require the LLM to cite the passages on which its recommendation is based.

### SKOS vocabulary generation

Approved concepts are represented in **SKOS** with:

* preferred label;
* alternative labels;
* broader concepts;
* narrower concepts;
* related concepts;
* definitions;
* editorial notes;
* source references.

SKOS is a W3C model for sharing and linking controlled vocabularies and other knowledge-organisation systems.

## Human role

Humans review clusters rather than every raw term.

Expert attention is required where:

* two legally distinct concepts use similar language;
* terminology has changed over time;
* one phrase has different meanings in different contexts;
* a proposed broader or narrower relationship affects reasoning.

## Deliverables

* SKOS vocabulary;
* synonym map;
* preferred-label register;
* broader and narrower concept hierarchy;
* rejected-term register;
* vocabulary governance process.

---

# Stage 4 — Extract relationships, propositions and candidate rules

## Objective

Move beyond identifying important terms and determine how those terms are connected.

## 4.1 Pattern-based relation extraction

Use spaCy’s **DependencyMatcher** and rule-based patterns to detect recurring grammatical structures. DependencyMatcher can match token relationships in parsed dependency trees.

Examples:

```text
[Case] interprets [Provision]
[Paragraph] cites [Case]
[Evidence] supports [Proposition]
[Exception] applies where [Condition]
[Instruction] replaces [Earlier instruction]
```

Pattern-based extraction is particularly useful for recurring and predictable wording.

## 4.2 LLM-based structured relation extraction

Use an approved LLM for complex relationships.

The prompt should:

* provide a limited list of allowed relationship types;
* require exact source spans;
* permit an `uncertain` response;
* require structured JSON;
* prohibit relationships not supported by the passage.

Example output:

```json
{
  "subject": "Cantarella decision",
  "relationship": "interprets",
  "object": "section 41",
  "supporting_text": "…",
  "confidence": 0.94
}
```

## 4.3 Candidate proposition extraction

Identify sentences that express:

* definitions;
* requirements;
* permissions;
* prohibitions;
* relevant factors;
* exceptions;
* conditions;
* procedural steps;
* consequences.

Use linguistic indicators such as:

* must;
* may;
* should;
* if;
* unless;
* only where;
* subject to;
* is defined as;
* is relevant to.

## 4.4 Candidate rule structuring

Represent candidate rules in a neutral intermediate format:

```json
{
  "rule_type": "procedural_requirement",
  "subject": "objection",
  "condition": "an objection is raised",
  "consequence": "the objection identifies a legislative basis",
  "modality": "must",
  "exceptions": [],
  "source": "paragraph-123",
  "review_status": "candidate"
}
```

This does not yet make the rule executable.

## Human role

Humans review:

* the meaning of high-impact relationships;
* whether “may” indicates permission or possibility;
* whether “must” is legal, procedural or explanatory;
* exceptions;
* rule priorities;
* potentially conflicting propositions;
* statements requiring evaluative judgment.

## Deliverables

* relationship candidates;
* proposition register;
* rule-candidate register;
* extraction patterns;
* confidence thresholds;
* review queue.

---

# Stage 5 — Formalise the ontology

## Objective

Define the reusable structure into which approved knowledge will be placed.

## Technologies

* RDF;
* RDFS;
* OWL 2 RL;
* SKOS;
* PROV-O;
* WebProtégé.

OWL provides formal vocabulary definitions and relationships. OWL 2 RL is specifically designed for scalable, rule-based reasoning while accepting reduced expressiveness compared with unrestricted OWL.

Protégé is an open-source OWL ontology editor, while WebProtégé provides a browser-based collaborative environment.

## Proposed ontology modules

### Examination module

* TradeMarkApplication;
* Examination;
* Examiner;
* Objection;
* ExaminationOutcome.

### Legal concepts module

* GroundOfRefusal;
* LegalTest;
* RelevantFactor;
* Exception;
* LegalProposition.

### Evidence module

* Evidence;
* EvidenceCategory;
* EvidenceSubmission;
* EvidentiaryProposition.

### Authority module

* Legislation;
* LegislativeProvision;
* JudicialDecision;
* ManualInstruction;
* Guidance;
* AuthorityStatus.

### Document module

* Document;
* DocumentVersion;
* Chapter;
* Paragraph;
* Passage.

### Time module

* effective date;
* superseded date;
* decision date;
* version applicability.

### Provenance module

* extraction process;
* reviewer;
* review date;
* confidence;
* source passage;
* inferred assertion.

PROV-O provides a standard foundation for recording entities, activities, agents and provenance relationships.

## Automated ontology generation

Python scripts should generate draft ontology content from:

* approved vocabulary records;
* approved entity types;
* approved relationship types;
* spreadsheet or database definitions;
* LLM-generated documentation drafts.

Use **RDFLib** to generate RDF and OWL files programmatically. RDFLib is a Python library for working with RDF graphs.

## Human role

Ontology specialists and domain experts approve:

* class definitions;
* relationship meanings;
* domain and range restrictions;
* disjoint categories;
* reasoning-relevant hierarchies;
* naming and identifier standards.

Humans should review the model, not manually type every individual graph record.

## Deliverables

* modular ontology;
* human-readable ontology guide;
* machine-readable RDF/OWL files;
* diagrams;
* approved relationship dictionary;
* automated generation scripts.

---

# Stage 6 — Populate and validate the knowledge graph

## Objective

Convert approved and high-confidence extracted knowledge into a governed graph.

## Automated process

For each approved assertion, generate RDF such as:

```text
Manual paragraph 4.3.12
    discussesConcept
Acquired distinctiveness

Manual paragraph 4.3.12
    citesProvision
Section 41

Court decision X
    interprets
Section 41
```

Each assertion must also record:

* exact source passage;
* source version;
* extraction method;
* confidence;
* review status;
* reviewer where applicable;
* creation date;
* applicable date range.

## Named graphs

Use separate named graphs for:

* authoritative source data;
* machine-extracted candidates;
* expert-approved assertions;
* inferred assertions;
* superseded assertions.

This prevents machine suggestions from appearing indistinguishable from approved knowledge.

## SHACL validation

Use **SHACL** to check the graph before publication. SHACL is a W3C language for defining constraints over RDF graphs.

Use **pySHACL** to run validation from the Python pipeline.

Example validation rules:

* every approved proposition must have a source passage;
* every source passage must identify a document version;
* every extracted relationship must identify its extraction method;
* every legislative provision must have a stable identifier;
* every superseded instruction must have a status date;
* every inferred result must identify the rule that produced it.

## Storage

Use **Apache Jena Fuseki** as the prototype RDF server. Fuseki exposes RDF data through SPARQL services.

A managed or commercial triple store may later replace Fuseki if production security, scale, support or operational requirements justify it.

## Human role

Humans resolve:

* validation failures that cannot be corrected deterministically;
* conflicting approved assertions;
* uncertain provenance;
* records that cross defined legal-risk thresholds.

## Deliverables

* populated knowledge graph;
* automated publication pipeline;
* SHACL rule library;
* validation reports;
* provenance records;
* SPARQL endpoint.

---

# Stage 7 — Build ontology-enhanced search

## Objective

Combine exact terminology, semantic similarity and graph relationships.

## Technology

Use **OpenSearch** for:

* BM25 keyword search;
* phrase search;
* field weighting;
* filters;
* vector search;
* hybrid ranking;
* aggregations.

OpenSearch hybrid search combines keyword and semantic queries and provides mechanisms for normalising and combining their scores.

## Index contents

Index each searchable passage with:

* passage text;
* heading;
* document title;
* version;
* authority type;
* effective dates;
* linked concepts;
* linked provisions;
* linked cases;
* review status;
* embedding vector;
* stable source identifier.

## Query process

For a question such as:

> Can marketplace use help overcome a distinctiveness objection?

the system should:

1. perform keyword search;
2. map “marketplace use” to related vocabulary concepts;
3. expand the query to “evidence of use” and “acquired distinctiveness”;
4. run vector similarity search;
5. query the graph for linked provisions and cases;
6. exclude superseded material;
7. combine and rerank the results.

## Reranking

Use either:

* OpenSearch hybrid score fusion;
* reciprocal rank fusion;
* a Sentence Transformers cross-encoder;
* an approved LLM reranker for a small final result set.

## Human role

Experts create search test questions and judge whether results are relevant. They should not manually tune individual searches.

## Deliverables

* search API;
* search interface;
* query-expansion service;
* relevance-ranking configuration;
* search benchmark;
* explainable result metadata.

---

# Stage 8 — Build graph-aware AI retrieval

## Objective

Provide an AI assistant with structured, current and traceable evidence.

## Retrieval sequence

### 1. Interpret the query

Use:

* vocabulary matching;
* entity recognition;
* embedding similarity;
* an LLM query classifier.

Extract:

* likely concepts;
* provisions;
* authority types;
* dates;
* procedural context.

### 2. Retrieve candidate passages

Run:

* OpenSearch keyword retrieval;
* vector retrieval;
* concept-expanded retrieval;
* graph traversal;
* metadata filters.

### 3. Expand through the graph

Retrieve directly connected:

* legislative provisions;
* cases;
* exceptions;
* related evidence categories;
* superseding instructions;
* broader and narrower concepts.

### 4. Rerank

Rank evidence by:

* textual relevance;
* semantic similarity;
* source authority;
* currency;
* graph proximity;
* expert-review status.

### 5. Construct the evidence package

Supply the AI with:

```json
{
  "interpreted_concepts": [],
  "source_passages": [],
  "legislative_provisions": [],
  "cases": [],
  "qualifications": [],
  "source_dates": [],
  "graph_relationships": [],
  "unresolved_uncertainties": []
}
```

### 6. Generate a grounded answer

Require the AI to:

* cite its source passages;
* distinguish legislation, case law and manual guidance;
* avoid unsupported conclusions;
* identify uncertainty;
* avoid representing an inferred relationship as direct source wording.

## Human role

Experts approve:

* the retrieval test set;
* source-authority weighting;
* treatment of superseded sources;
* high-risk answer templates;
* escalation rules.

Routine retrieval should be automatic.

## Deliverables

* graph-aware retrieval API;
* evidence-package schema;
* AI grounding controls;
* citation service;
* retrieval evaluation suite;
* audit logs.

---

# Stage 9 — Introduce automated reasoning

## Objective

Use approved knowledge to produce limited, explainable inferences.

## Reasoning technology

Use:

* RDFS and OWL 2 RL inference;
* Apache Jena’s reasoning support;
* SPARQL queries;
* SPARQL `CONSTRUCT` rules for explicit derived relationships;
* SHACL for completeness and validation;
* decision tables for selected procedural logic.

Apache Jena includes inference support and rule engines for deriving consequences from RDF models.

## Reasoning levels

### Level 1 — Classification

Example:

```text
AcquiredDistinctiveness
    subclassOf
Distinctiveness
```

Material about acquired distinctiveness can therefore also be classified as relevant to distinctiveness.

### Level 2 — Relationship propagation

If:

```text
Paragraph A discusses AcquiredDistinctiveness
AcquiredDistinctiveness is narrower than Distinctiveness
```

the system may infer:

```text
Paragraph A is relevant to Distinctiveness
```

### Level 3 — Impact analysis

If:

```text
Manual instruction A is based on Provision B
Provision B is amended
```

the system can flag:

* instruction A;
* linked examples;
* linked AI retrieval pathways;
* linked training material;

for review.

### Level 4 — Consistency checking

The system can detect:

* incompatible classifications;
* circular or impossible hierarchies;
* missing authority links;
* overlapping concepts declared mutually exclusive.

### Level 5 — Selected procedural rules

Simple, explicit rules may be automated, for example:

> An approved objection record must identify at least one legislative basis.

This is mainly a validation rule.

Evaluative conclusions such as:

> The evidence establishes acquired distinctiveness

should remain outside the initial automated reasoning scope.

## Reasoning explanations

Every inferred assertion must identify:

* the source facts;
* the ontology axiom or rule;
* the date the inference was generated;
* whether human review is required.

## Human role

Experts approve every reasoning template before deployment.

They review:

* novel rule types;
* exceptions;
* conflicting authorities;
* rules that may affect substantive examination conclusions.

Once a rule has been approved and fully tested, its routine execution is automatic.

## Deliverables

* OWL reasoning configuration;
* SPARQL rule library;
* reasoning test suite;
* explanation records;
* prohibited-inference tests;
* review and escalation rules.

---

# Stage 10 — Automate maintenance and continuous improvement

## Objective

Ensure that the knowledge system remains current without remodelling the corpus manually.

## Automated update pipeline

When a source changes:

1. detect the changed document;
2. identify changed passages;
3. process only the affected passages;
4. rerun keyphrase and entity extraction;
5. rerun relationship and proposition extraction;
6. compare new output with existing graph records;
7. automatically retain unchanged assertions;
8. queue materially changed legal assertions for review;
9. rerun SHACL validation;
10. rerun search, retrieval and reasoning regression tests;
11. publish the approved update.

## Active learning

Use expert decisions to improve extraction.

Examples:

* accepted entity labels become EntityRuler patterns;
* rejected terms become negative examples;
* corrected relationships become training data;
* recurring review decisions become deterministic rules;
* low-confidence categories can be prioritised for model improvement.

## Monitoring

Track:

* extraction confidence;
* review rejection rate;
* unresolved citations;
* validation failures;
* search quality;
* retrieval precision;
* unsupported AI claims;
* reasoning errors;
* time from source change to publication.

## Human role

Humans focus on changed, uncertain or high-risk material rather than rereading the entire corpus.

## Deliverables

* incremental update pipeline;
* active-learning dataset;
* quality dashboard;
* versioned graph releases;
* audit history;
* rollback process.

---

# 5. Evaluation framework

## NLP extraction

Measure:

* entity precision, recall and F1;
* citation-resolution accuracy;
* relationship precision and recall;
* synonym-clustering accuracy;
* proportion of records requiring review;
* expert rejection rate.

## Search

Measure:

* Recall@10;
* Precision@10;
* mean reciprocal rank;
* nDCG;
* successful retrieval using alternative terminology;
* retrieval of current rather than superseded sources.

## AI retrieval

Measure:

* expected source coverage;
* retrieval precision;
* noise in the evidence package;
* citation correctness;
* grounding;
* authority weighting;
* use of current sources.

## Automated reasoning

Measure:

* expected inferences produced;
* prohibited inferences produced;
* consistency-check accuracy;
* impact-analysis coverage;
* explanation completeness;
* expert agreement.

## Operational efficiency

Measure:

* number of passages processed automatically;
* expert minutes per 100 passages;
* proportion of records accepted without intervention;
* processing cost;
* time required to incorporate a changed source.

The objective is not to eliminate all human involvement. It is to use limited expert time where it adds the most value.

---

# 6. Suggested human review policy

| Output type                | Initial policy            | Mature-state policy                          |
| -------------------------- | ------------------------- | -------------------------------------------- |
| Document segmentation      | Sample review             | Automated with exception review              |
| Exact legislative citation | Review unresolved cases   | Automated with sample audit                  |
| YAKE keyword               | Bulk review               | Automatic candidate generation               |
| Known entity match         | Sample review             | Automatic                                    |
| New concept suggestion     | Expert approval           | Confidence-based review                      |
| Synonym recommendation     | Expert approval           | High-confidence auto-merge with audit        |
| Routine relationship       | Expert approval           | High-confidence auto-accept by relation type |
| Legal exception            | Mandatory expert approval | Mandatory expert approval                    |
| Executable rule            | Mandatory expert approval | Mandatory expert approval                    |
| SHACL validation result    | Automatic                 | Automatic                                    |
| OWL inference              | Test and approve rule     | Automatic execution with logging             |
| AI answer                  | Automated with citations  | Automated with monitoring and escalation     |

---

# 7. Role of LegalRuleML

LegalRuleML should not be included in the initial implementation.

The proposed system can achieve its first reasoning goals using:

* OWL 2 RL for classifications and semantic relationships;
* SHACL for validation;
* SPARQL for graph queries and explicit derivations;
* decision tables for bounded procedural rules.

LegalRuleML becomes relevant only if the organisation later needs to formally represent and exchange complex legal rules involving:

* obligations;
* permissions;
* prohibitions;
* defeasible conclusions;
* explicit rule priorities;
* competing interpretations;
* complex temporal or jurisdictional applicability.

Before introducing it, the team should prove that simpler reasoning approaches are inadequate for a defined use case.

---

# 8. Recommended pilot outcome

A successful pilot should demonstrate that most source-processing work can be completed automatically.

For a bounded examination area, the pilot should produce:

* a parsed and versioned source corpus;
* an automatically generated candidate vocabulary;
* a reviewed SKOS concept scheme;
* an OWL ontology;
* automatically extracted entities and relationships;
* a validated knowledge graph;
* an ontology-enhanced search interface;
* graph-aware AI retrieval;
* several approved reasoning examples;
* an incremental update process;
* evidence showing how much expert effort was saved.

The pilot should not attempt to automate the final examination decision.

---

# 9. Recommended implementation order

## Release 1 — Automated discovery

Build:

* document parsing;
* YAKE extraction;
* citation detection;
* known entity matching;
* embedding-based term clustering;
* review interface.

## Release 2 — Vocabulary and knowledge graph

Build:

* SKOS vocabulary;
* ontology modules;
* relationship extraction;
* provenance;
* RDF generation;
* SHACL validation;
* Fuseki graph service.

## Release 3 — Search and AI retrieval

Build:

* OpenSearch index;
* hybrid search;
* vocabulary expansion;
* graph traversal;
* AI evidence packages;
* citations and retrieval evaluation.

## Release 4 — Bounded reasoning

Build:

* OWL 2 RL reasoning;
* impact analysis;
* consistency checks;
* approved SPARQL rules;
* reasoning explanations.

## Release 5 — Continuous maintenance

Build:

* source-change detection;
* incremental reprocessing;
* active learning;
* automated regression testing;
* production monitoring.

---

# Final recommendation

Do not begin by manually constructing the entire ontology.

Begin with a small expert-created test set and use automated document processing, YAKE, spaCy, embeddings and structured LLM extraction to generate the first vocabulary, entities, relationships and propositions.

Use human experts primarily to:

* approve the model;
* resolve ambiguity;
* verify important legal meaning;
* validate reasoning rules;
* audit automated performance.

The operating principle should be:

> **Machines extract, cluster, link and propose.
> Experts define, approve and resolve exceptions.
> The ontology formalises approved meaning.
> SHACL protects data quality.
> Search and AI retrieve the evidence.
> Reasoning operates only over governed knowledge.**

This approach avoids starting from scratch while preserving the traceability, accountability and precision required for legal knowledge.
