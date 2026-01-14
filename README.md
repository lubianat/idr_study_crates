# IDR Metadata to RO-Crate 1.2

Simple Python converter that parses an IDR metadata text file and emits a RO-Crate 1.2 `ro-crate-metadata.json`, plus a reverse converter back to IDR text.

## Features

- Class-based decoder/encoder (`IDRDecoder`, `ROCrateEncoder`) with a reverse path (`ROCrateDecoder`, `IDREncoder`).
- Emits linked-data terms for ontology-backed study fields (e.g., Study Type).
- Keeps remaining study rows as `PropertyValue` entries for completeness.
- Includes screen/experiment sections as separate datasets in the RO-Crate output.

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
python3 -m unittest discover -s tests
```

If you prefer pytest:

```
pytest
```

## Batch Generation

Generate RO-Crates for all `idr*-study.txt` files under `examples/`:

```
python3 scripts/batch_generate.py --input-dir examples --output-dir ro-crates
```

## Acknowledgements

This converter is built around the IDR study metadata format and templates from the `IDR/idr-metadata` repository:
`https://github.com/IDR/idr-metadata`.
## Profile crate

The repository includes a draft RO-Crate profile for the generated IDR crates in `profile/`.
The profile URI is `https://idr.openmicroscopy.org/ro-crate/profile/0.1`, and generated
crates declare conformance using `conformsTo` on the root dataset.
