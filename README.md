# IDR Metadata to RO-Crate 1.2

Simple Python converter that parses an IDR metadata text file and emits a RO-Crate 1.2 `<accession>-ro-crate-metadata.json` (or `ro-crate-metadata.json` when no accession is available), plus a reverse converter back to IDR text.

## Features

- Class-based decoder/encoder (`IDRDecoder`, `ROCrateEncoder`) with a reverse path (`ROCrateDecoder`, `IDREncoder`).
- Emits linked-data terms for ontology-backed study fields (e.g., Study Type).
- Keeps remaining study rows as `PropertyValue` entries for completeness.
- Includes screen/experiment sections as separate datasets in the RO-Crate output.
- Supports optional FBBI and NCBITaxon hierarchy subset exports from the merged Turtle output.

## Requirements

- Python 3.8+ (use `python3` if `python` is not available)

## Usage

Forward conversion:

```
python3 idr_rocrate.py path/to/idr_metadata.txt -o ro-crate-metadata.json
```

Reverse conversion:

```
python3 idr_rocrate.py ro-crate-metadata.json --reverse -o idr-metadata.txt
```

Optional encoding override:

```
python3 idr_rocrate.py path/to/idr_metadata.txt --encoding utf-8 -o ro-crate-metadata.json
```

## Input Expectations

- Tab-delimited lines: `Key<TAB>Value<TAB>Value...`
- If no tabs are present, the parser falls back to splitting on 2+ spaces.
- Template hints that start with `#` are treated as empty for mapping.

## Output Highlights

- Detached RO-Crate Root `@id` uses the IDR study URL when an accession is present, e.g. `https://idr.openmicroscopy.org/study/idr0001/`.
- Ontology-backed fields become `DefinedTerm` entities with:
  - `termCode` and `identifier` from the accession (e.g., `EFO_0007550`)
  - `inDefinedTermSet` pointing to the term source URI
- Study DOI is treated as a publication DOI and emitted via `citation`.
- Study Data DOI (when provided) is treated as the dataset DOI and emitted via `identifier` and `cite-as`.
- All remaining study rows are emitted as `PropertyValue` objects on the root dataset.

## Examples

Sample inputs:

- `examples/idr0001.txt`
- `examples/idr0002.txt`
- `examples/studies/` (copied from `idr-metadata-0.12.8`)

## Tests

```
uv run pytest
```

## Batch Generation

Generate RO-Crates for all `idr*-study.txt` files under `examples/`:

```
uv run scripts/batch_generate.py --input-dir examples --output-dir ro-crates
```

Add `--verbose` to log per-crate output paths while processing.

## Turtle Export

To merge all generated RO-Crates into a single Turtle file:

```
uv run scripts/batch_generate.py --input-dir examples --output-dir ro-crates --ttl-out ro-crates/idr-studies.ttl
```

Relative identifiers are resolved against each crate's `<accession>-ro-crate-metadata.json` file URI.

## FBBI/NCBITaxon Hierarchy Export

After generating `ro-crates/idr-studies.ttl`, run:

```
python3 scripts/join_with_fbbi_and_ncbitaxon.py
```

This reads ontology inputs from `ontologies/raw/` (see `ontologies/README.md`) and writes:

- `ontologies/extracted/idr_fbbi_hierarchy_subset.ttl`
- `ontologies/extracted/idr_ncbitaxon_hierarchy_subset.ttl`
- `ro-crates/idr-studies-with-ontology-subsets.ttl`

## Acknowledgements

This converter is built around the IDR study metadata format and templates from the `IDR/idr-metadata` repository:
`https://github.com/IDR/idr-metadata`.
## Profile crate

The repository includes a draft RO-Crate profile for the generated IDR crates in `profile/`.
The profile URI is `https://idr.openmicroscopy.org/ro-crate/profile/0.1`, and generated
crates declare conformance using `conformsTo` on the root dataset.
