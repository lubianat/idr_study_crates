#!/usr/bin/env python3

from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IDR_STUDIES_TTL = ROOT / "ro-crates/idr-studies.ttl"
FBBI_OWL = ROOT / "ontologies/raw/fbbi.owl"
NCBITAXON_TSV = ROOT / "ontologies/raw/ncbitaxon_hierarchy_wikidata.tsv"

OUT_DIR = ROOT / "ontologies/extracted"
OUT_FBBI_TTL = OUT_DIR / "idr_fbbi_hierarchy_subset.ttl"
OUT_NCBI_TTL = OUT_DIR / "idr_ncbitaxon_hierarchy_subset.ttl"
OUT_JOINT_TTL = ROOT / "ro-crates/idr-studies-with-ontology-subsets.ttl"

OBO_BASE = "http://purl.obolibrary.org/obo/"

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
OWL_NS = "http://www.w3.org/2002/07/owl#"
XML_NS = "http://www.w3.org/XML/1998/namespace"

NS = {"rdf": RDF_NS, "rdfs": RDFS_NS, "owl": OWL_NS}

FBBI_USE_RE = re.compile(r"\bobo:FBBI_(\d+)\b")
NCBI_USE_RE = re.compile(r"\bobo:NCBITaxon_(\d+)\b")
NCBI_DEF_RE = re.compile(
    r"obo:NCBITaxon_(\d+)\s+a\s+dwc:Taxon\s*;\s*dwc:scientificName\s+\"([^\"]+)\"\s*\.",
    re.MULTILINE | re.DOTALL,
)


def ttl_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def output_fbbi_id(local_id: str) -> str:
    if re.fullmatch(r"FBbi_\d+", local_id):
        return "FBBI_" + local_id.split("_", 1)[1]
    return local_id


def read_seeds_from_idr_ttl() -> tuple[set[str], set[str], dict[str, str]]:
    text = IDR_STUDIES_TTL.read_text(encoding="utf-8")
    fbbi_seeds = {f"FBbi_{digits}" for digits in FBBI_USE_RE.findall(text)}
    ncbi_seeds = {digits for digits in NCBI_USE_RE.findall(text)}

    ncbi_names: dict[str, str] = {}
    for digits, name in NCBI_DEF_RE.findall(text):
        ncbi_names[digits] = name
    return fbbi_seeds, ncbi_seeds, ncbi_names


def parse_fbbi_ontology() -> tuple[dict[str, str], dict[str, set[str]]]:
    tree = ET.parse(FBBI_OWL)
    root = tree.getroot()

    labels: dict[str, str] = {}
    parents: dict[str, set[str]] = {}

    for class_elem in root.findall(".//owl:Class", NS):
        about = class_elem.attrib.get(f"{{{RDF_NS}}}about", "")
        if not about.startswith(OBO_BASE):
            continue
        child = about[len(OBO_BASE) :]

        label = ""
        for lbl in class_elem.findall("rdfs:label", NS):
            if not lbl.text:
                continue
            text = lbl.text.strip()
            if not text:
                continue
            lang = lbl.attrib.get(f"{{{XML_NS}}}lang", "")
            if lang.lower() == "en":
                label = text
                break
            if not label and not lang:
                label = text
            if not label:
                label = text
        labels[child] = label

        child_parents: set[str] = set()
        for sub in class_elem.findall("rdfs:subClassOf", NS):
            parent_uri = sub.attrib.get(f"{{{RDF_NS}}}resource", "")
            if parent_uri.startswith(OBO_BASE):
                child_parents.add(parent_uri[len(OBO_BASE) :])
        parents[child] = child_parents

    return labels, parents


def fbbi_closure(seed_ids: set[str], parents: dict[str, set[str]]) -> set[str]:
    selected: set[str] = set()
    stack = [sid for sid in seed_ids if sid in parents]

    while stack:
        current = stack.pop()
        if current in selected:
            continue
        selected.add(current)
        for parent in parents.get(current, set()):
            if parent in parents and parent not in selected:
                stack.append(parent)
    return selected


def write_fbbi_subset_ttl(selected: set[str], labels: dict[str, str], parents: dict[str, set[str]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_FBBI_TTL.open("w", encoding="utf-8") as f:
        f.write("@prefix obo: <http://purl.obolibrary.org/obo/> .\n")
        f.write("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n")
        f.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n")

        for child in sorted(selected, key=output_fbbi_id):
            triples = [f"obo:{output_fbbi_id(child)} a owl:Class"]
            label = labels.get(child, "")
            if label:
                triples.append(f'rdfs:label "{ttl_escape(label)}"')

            sel_parents = sorted(p for p in parents.get(child, set()) if p in selected)
            if sel_parents:
                parent_list = ", ".join(f"obo:{output_fbbi_id(p)}" for p in sel_parents)
                triples.append(f"rdfs:subClassOf {parent_list}")

            f.write(" ;\n    ".join(triples) + " .\n\n")


def clean_tsv_field(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_ncbi_selected(
    seed_ids: set[str], base_names: dict[str, str]
) -> tuple[set[str], dict[str, str], dict[str, set[str]]]:
    selected = set(seed_ids)
    names = dict(base_names)

    # First pass: collect all ancestors for IDR taxa.
    with NCBITAXON_TSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader)
        for row in reader:
            a_id = clean_tsv_field(row[1])
            b_id = clean_tsv_field(row[3])
            a_name = clean_tsv_field(row[4])
            b_name = clean_tsv_field(row[5])
            if a_id in seed_ids:
                selected.add(b_id)
                names.setdefault(a_id, a_name)
                names.setdefault(b_id, b_name)

    # Second pass: build ancestor relations only among selected terms.
    ancestors: dict[str, set[str]] = {}
    with NCBITAXON_TSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader)
        for row in reader:
            a_id = clean_tsv_field(row[1])
            b_id = clean_tsv_field(row[3])
            a_name = clean_tsv_field(row[4])
            b_name = clean_tsv_field(row[5])
            if a_id in selected:
                names.setdefault(a_id, a_name)
            if b_id in selected:
                names.setdefault(b_id, b_name)
            if a_id in selected and b_id in selected and a_id != b_id:
                ancestors.setdefault(a_id, set()).add(b_id)

    return selected, names, ancestors


def direct_ncbi_parents(selected: set[str], ancestors: dict[str, set[str]]) -> dict[str, set[str]]:
    direct: dict[str, set[str]] = {}
    for child in selected:
        candidates = set(ancestors.get(child, set()))
        keep = set(candidates)
        for parent in candidates:
            for intermediate in candidates:
                if intermediate == parent:
                    continue
                if parent in ancestors.get(intermediate, set()):
                    keep.discard(parent)
                    break
        direct[child] = keep
    return direct


def write_ncbi_subset_ttl(selected: set[str], names: dict[str, str], direct_parents: dict[str, set[str]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_NCBI_TTL.open("w", encoding="utf-8") as f:
        f.write("@prefix obo: <http://purl.obolibrary.org/obo/> .\n")
        f.write("@prefix dwc: <http://rs.tdwg.org/dwc/terms/> .\n")
        f.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n")

        for taxon_id in sorted(selected, key=int):
            triples = [f"obo:NCBITaxon_{taxon_id} a dwc:Taxon"]
            label = names.get(taxon_id, "")
            if label:
                escaped = ttl_escape(label)
                triples.append(f'rdfs:label "{escaped}"')
                triples.append(f'dwc:scientificName "{escaped}"')
            parents = sorted(direct_parents.get(taxon_id, set()), key=int)
            if parents:
                parent_list = ", ".join(f"obo:NCBITaxon_{parent}" for parent in parents)
                triples.append(f"rdfs:subClassOf {parent_list}")
            f.write(" ;\n    ".join(triples) + " .\n\n")


def write_joint_export_ttl() -> None:
    idr_text = IDR_STUDIES_TTL.read_text(encoding="utf-8").rstrip()
    fbbi_text = OUT_FBBI_TTL.read_text(encoding="utf-8").rstrip()
    ncbi_text = OUT_NCBI_TTL.read_text(encoding="utf-8").rstrip()

    # Keep each source block intact for traceability while producing one merged export.
    merged = (
        f"{idr_text}\n\n"
        "# ---- Extracted FBBI hierarchy subset ----\n"
        f"{fbbi_text}\n\n"
        "# ---- Extracted NCBITaxon hierarchy subset ----\n"
        f"{ncbi_text}\n"
    )
    OUT_JOINT_TTL.write_text(merged, encoding="utf-8")


def main() -> None:
    fbbi_seeds, ncbi_seeds, ncbi_seed_names = read_seeds_from_idr_ttl()

    fbbi_labels, fbbi_parents = parse_fbbi_ontology()
    fbbi_selected = fbbi_closure(fbbi_seeds, fbbi_parents)
    write_fbbi_subset_ttl(fbbi_selected, fbbi_labels, fbbi_parents)

    ncbi_selected, ncbi_names, ncbi_ancestors = parse_ncbi_selected(ncbi_seeds, ncbi_seed_names)
    ncbi_direct = direct_ncbi_parents(ncbi_selected, ncbi_ancestors)
    write_ncbi_subset_ttl(ncbi_selected, ncbi_names, ncbi_direct)
    write_joint_export_ttl()

    print(f"Wrote {OUT_FBBI_TTL}")
    print(f"Wrote {OUT_NCBI_TTL}")
    print(f"Wrote {OUT_JOINT_TTL}")
    print(f"FBBI terms: {len(fbbi_selected)}")
    print(f"NCBITaxon terms: {len(ncbi_selected)}")


if __name__ == "__main__":
    main()
