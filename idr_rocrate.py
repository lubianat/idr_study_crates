#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class IDRRow:
    key: str
    values: List[str]
    line_no: int
    section: Optional[str] = None

    def has_value(self) -> bool:
        return any(v.strip() for v in self.values)


@dataclass
class IDRMetadata:
    raw_text: str
    rows: List[IDRRow]

    def rows_for_key(self, key: str) -> List[IDRRow]:
        return [row for row in self.rows if row.key == key]

    def first_value(self, key: str, rows: Optional[List[IDRRow]] = None) -> Optional[str]:
        for row in rows or self.rows:
            if row.key != key:
                continue
            for value in row.values:
                if value.strip():
                    return value.strip()
        return None

    def values_for_key(self, key: str, rows: Optional[List[IDRRow]] = None) -> List[str]:
        for row in rows or self.rows:
            if row.key == key:
                return row.values
        return []

    def split_study_rows(self) -> Tuple[List[IDRRow], List[IDRRow]]:
        for idx, row in enumerate(self.rows):
            if row.key in ("Screen Number", "Experiment Number") and row.has_value():
                return self.rows[:idx], self.rows[idx:]
        return self.rows, []

    def term_source_map(self) -> Dict[str, str]:
        names = self.values_for_key("Term Source Name")
        uris = self.values_for_key("Term Source File")
        if not uris:
            uris = self.values_for_key("Term Source URI")
        mapping = {}
        for name, uri in zip(names, uris):
            name = name.strip()
            uri = uri.strip()
            if name and uri:
                mapping[name] = uri
        return mapping


class IDRDecoder:
    def __init__(self, encoding: str = "utf-8") -> None:
        self.encoding = encoding

    def decode(self, path: Path) -> IDRMetadata:
        raw_text = path.read_text(encoding=self.encoding)
        return self.decode_text(raw_text)

    def decode_text(self, raw_text: str) -> IDRMetadata:
        rows = self._parse_text(raw_text)
        return IDRMetadata(raw_text=raw_text, rows=rows)

    def _parse_text(self, raw_text: str) -> List[IDRRow]:
        rows: List[IDRRow] = []
        current_section: Optional[str] = None
        for line_no, raw_line in enumerate(raw_text.splitlines(), start=1):
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                current_section = stripped.lstrip("#").strip() or None
                continue
            if "\t" in line:
                parts = line.split("\t")
            else:
                parts = re.split(r"\s{2,}", line)
            key = parts[0].strip()
            values = [clean_value(part) for part in parts[1:]]
            values = trim_trailing_empty(values)
            if not values:
                continue
            rows.append(IDRRow(key=key, values=values, line_no=line_no, section=current_section))
        return rows


class IDREncoder:
    def encode(self, metadata: IDRMetadata) -> str:
        if metadata.raw_text:
            return metadata.raw_text
        return self.encode_rows(metadata.rows)

    def encode_rows(self, rows: Iterable[IDRRow]) -> str:
        lines: List[str] = []
        for row in rows:
            if not row.key:
                continue
            if row.values:
                line = f"{row.key}\t" + "\t".join(row.values)
            else:
                line = row.key
            lines.append(line)
        if not lines:
            return ""
        return "\n".join(lines) + "\n"


class GraphBuilder:
    def __init__(self) -> None:
        self._entities: Dict[str, dict] = {}
        self._order: List[str] = []

    def add(self, entity: dict) -> None:
        entity_id = entity["@id"]
        if entity_id in self._entities:
            self._entities[entity_id].update(entity)
            return
        self._entities[entity_id] = entity
        self._order.append(entity_id)

    def to_list(self) -> List[dict]:
        return [self._entities[entity_id] for entity_id in self._order]


class ROCrateEncoder:
    def encode(self, metadata: IDRMetadata) -> dict:
        graph = GraphBuilder()
        context = [
            "https://w3id.org/ro/crate/1.2/context",
            {
                "text": "http://schema.org/text",
                "additionalProperty": "http://schema.org/additionalProperty",
                "value": "http://schema.org/value",
                "propertyID": "http://schema.org/propertyID",
                "termCode": "http://schema.org/termCode",
                "inDefinedTermSet": "http://schema.org/inDefinedTermSet",
                "measurementTechnique": "http://schema.org/measurementTechnique",
                "category": "http://schema.org/category",
                "studyType": "http://schema.org/additionalType",
                "screenImagingMethod": "http://schema.org/measurementTechnique",
                "screenTechnologyType": "http://schema.org/additionalType",
                "screenType": "http://schema.org/category",
                "experimentImagingMethod": "http://schema.org/measurementTechnique",
            },
        ]

        study_rows, _ = metadata.split_study_rows()
        term_sources = metadata.term_source_map()
        term_set_map = build_term_set_map(term_sources)
        add_term_sets(graph, term_set_map)
        accession = metadata.first_value("Comment[IDR Study Accession]", study_rows)
        study_external_url = metadata.first_value("Study External URL", study_rows)
        root_id = build_root_id(accession, study_external_url)
        graph.add(
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
                "about": {"@id": root_id},
                "description": "RO-Crate metadata generated from IDR metadata",
            }
        )

        root = {
            "@id": root_id,
            "@type": "Dataset",
        }

        title = metadata.first_value("Study Title", study_rows)
        if title:
            root["name"] = title
        description = metadata.first_value("Study Description", study_rows)
        if description:
            root["description"] = description
        pub_date = metadata.first_value("Study Public Release Date", study_rows)
        if pub_date:
            root["datePublished"] = pub_date

        keywords = [v for v in metadata.values_for_key("Study Key Words", study_rows) if v.strip()]
        if keywords:
            root["keywords"] = ", ".join(keywords)

        if study_external_url:
            root["url"] = normalize_url(study_external_url)

        identifiers: List[str] = []
        if accession:
            identifiers.append(accession)
        data_doi = metadata.first_value("Study Data DOI", study_rows)
        study_doi = metadata.first_value("Study DOI", study_rows)
        study_doi_url = normalize_doi(study_doi) if study_doi else None
        data_doi_url = normalize_doi(data_doi) if data_doi else None
        if data_doi_url:
            identifiers.append(data_doi_url)
            root["cite-as"] = data_doi_url
            if data_doi_url != study_doi_url:
                graph.add(
                    {
                        "@id": data_doi_url,
                        "@type": "PropertyValue",
                        "propertyID": "https://registry.identifiers.org/registry/doi",
                        "value": f"doi:{data_doi_url.replace('https://doi.org/', '')}",
                        "url": data_doi_url,
                    }
                )
        if identifiers:
            root["identifier"] = identifiers if len(identifiers) > 1 else identifiers[0]

        license_name = metadata.first_value("Study License", study_rows)
        license_url = metadata.first_value("Study License URL", study_rows)
        if license_name or license_url:
            license_id = normalize_url(license_url) if license_url else "#license"
            license_entity = {
                "@id": license_id,
                "@type": "CreativeWork",
                "name": license_name or license_id,
            }
            if license_url:
                license_entity["url"] = normalize_url(license_url)
            graph.add(license_entity)
            root["license"] = {"@id": license_id}

        copyright_holder = metadata.first_value("Study Copyright", study_rows)
        if copyright_holder:
            root["copyrightHolder"] = copyright_holder

        study_type = metadata.first_value("Study Type", study_rows)
        study_type_accession = metadata.first_value("Study Type Term Accession", study_rows)
        study_type_source = metadata.first_value("Study Type Term Source REF", study_rows)
        if study_type or study_type_accession:
            term_id, term_entity = build_defined_term(
                study_type,
                study_type_accession,
                study_type_source,
                term_sources,
                term_set_map,
                fallback_prefix="study-type",
            )
            graph.add(term_entity)
            root["studyType"] = {"@id": term_id}

        organism_values = metadata.values_for_key("Study Organism", study_rows)
        organism_accessions = metadata.values_for_key("Study Organism Term Accession", study_rows)
        organism_source = metadata.first_value("Study Organism Term Source REF", study_rows)
        organism_ids = []
        for idx, org_name in enumerate(organism_values):
            if not org_name.strip():
                continue
            accession_value = organism_accessions[idx] if idx < len(organism_accessions) else ""
            term_id, term_entity = build_defined_term(
                org_name,
                accession_value,
                organism_source,
                term_sources,
                term_set_map,
                fallback_prefix="organism",
            )
            graph.add(term_entity)
            organism_ids.append({"@id": term_id})
        if organism_ids:
            root["about"] = organism_ids if len(organism_ids) > 1 else organism_ids[0]

        people = parse_people(study_rows)
        if people:
            root["author"] = [{"@id": person["@id"]} for person in people]
            for person in people:
                graph.add(person)

        publication = build_publication(study_rows)
        if publication:
            root["citation"] = {"@id": publication["@id"]}
            graph.add(publication)

        study_author_list = metadata.first_value("Study Author List", study_rows)
        if study_author_list:
            root["creditText"] = study_author_list

        root["additionalProperty"] = rows_to_property_values(study_rows)

        screen_blocks = find_blocks(metadata.rows, "Screen Number", stop_keys=["Experiment Number"])
        screen_ids = []
        for idx, block in enumerate(screen_blocks, start=1):
            screen_number = first_value_in_block(block, "Screen Number") or str(idx)
            screen_name = first_value_in_block(block, "Comment[IDR Screen Name]") or f"Screen {screen_number}"
            screen_description = first_value_in_block(block, "Screen Description")
            screen_id = f"#screen-{screen_number}"
            screen = {
                "@id": screen_id,
                "@type": "Dataset",
                "name": screen_name,
                "additionalProperty": rows_to_property_values(block),
            }
            if screen_description:
                screen["description"] = screen_description

            imaging_method = first_value_in_block(block, "Screen Imaging Method")
            imaging_accession = first_value_in_block(block, "Screen Imaging Method Term Accession")
            imaging_source = first_value_in_block(block, "Screen Imaging Method Term Source REF")
            if imaging_method or imaging_accession:
                term_id, term_entity = build_defined_term(
                    imaging_method,
                    imaging_accession,
                    imaging_source,
                    term_sources,
                    term_set_map,
                    fallback_prefix="screen-imaging",
                )
                graph.add(term_entity)
                screen["screenImagingMethod"] = {"@id": term_id}

            technology_type = first_value_in_block(block, "Screen Technology Type") or first_value_in_block(
                block, "Screen Technology"
            )
            technology_accession = first_value_in_block(block, "Screen Technology Type Term Accession") or first_value_in_block(
                block, "Screen Technology Term Accession"
            )
            technology_source = first_value_in_block(block, "Screen Technology Type Term Source REF") or first_value_in_block(
                block, "Screen Technology Term Source REF"
            )
            if technology_type or technology_accession:
                term_id, term_entity = build_defined_term(
                    technology_type,
                    technology_accession,
                    technology_source,
                    term_sources,
                    term_set_map,
                    fallback_prefix="screen-technology",
                )
                graph.add(term_entity)
                screen["screenTechnologyType"] = {"@id": term_id}

            screen_type = first_value_in_block(block, "Screen Type")
            screen_type_accession = first_value_in_block(block, "Screen Type Term Accession")
            screen_type_source = first_value_in_block(block, "Screen Type Term Source REF")
            if screen_type or screen_type_accession:
                term_id, term_entity = build_defined_term(
                    screen_type,
                    screen_type_accession,
                    screen_type_source,
                    term_sources,
                    term_set_map,
                    fallback_prefix="screen-type",
                )
                graph.add(term_entity)
                screen["screenType"] = {"@id": term_id}

            graph.add(screen)
            screen_ids.append({"@id": screen_id})

        experiment_blocks = find_blocks(metadata.rows, "Experiment Number", stop_keys=["Screen Number"])
        experiment_ids = []
        for idx, block in enumerate(experiment_blocks, start=1):
            experiment_number = first_value_in_block(block, "Experiment Number") or str(idx)
            experiment_name = first_value_in_block(block, "Comment[IDR Experiment Name]") or f"Experiment {experiment_number}"
            experiment_description = first_value_in_block(block, "Experiment Description")
            experiment_id = f"#experiment-{experiment_number}"
            experiment = {
                "@id": experiment_id,
                "@type": "Dataset",
                "name": experiment_name,
                "additionalProperty": rows_to_property_values(block),
            }
            if experiment_description:
                experiment["description"] = experiment_description

            imaging_method = first_value_in_block(block, "Experiment Imaging Method")
            imaging_accession = first_value_in_block(block, "Experiment Imaging Method Term Accession")
            imaging_source = first_value_in_block(block, "Experiment Imaging Method Term Source REF")
            if imaging_method or imaging_accession:
                term_id, term_entity = build_defined_term(
                    imaging_method,
                    imaging_accession,
                    imaging_source,
                    term_sources,
                    term_set_map,
                    fallback_prefix="experiment-imaging",
                )
                graph.add(term_entity)
                experiment["experimentImagingMethod"] = {"@id": term_id}

            graph.add(experiment)
            experiment_ids.append({"@id": experiment_id})

        has_part = []
        if screen_ids:
            has_part.extend(screen_ids)
        if experiment_ids:
            has_part.extend(experiment_ids)
        if has_part:
            root["hasPart"] = has_part

        graph.add(root)
        return {"@context": context, "@graph": graph.to_list()}


class ROCrateDecoder:
    def __init__(self, encoding: str = "utf-8") -> None:
        self.encoding = encoding

    def decode_path(self, path: Path) -> IDRMetadata:
        raw_json = path.read_text(encoding=self.encoding)
        crate = json.loads(raw_json)
        return self.decode_data(crate)

    def decode_data(self, crate: dict) -> IDRMetadata:
        graph = crate.get("@graph", [])
        if not isinstance(graph, list):
            raise ValueError("RO-Crate @graph must be a list")

        entity_map = {entity.get("@id"): entity for entity in graph if isinstance(entity, dict) and entity.get("@id")}
        root_entity = find_root_entity(entity_map)

        rows: List[IDRRow] = []
        if root_entity:
            rows.extend(rows_from_property_values(root_entity.get("additionalProperty"), entity_map))
            for part_ref in as_list(root_entity.get("hasPart")):
                part_entity = resolve_entity(part_ref, entity_map)
                if part_entity:
                    rows.extend(rows_from_property_values(part_entity.get("additionalProperty"), entity_map))

        raw_text = IDREncoder().encode_rows(rows)
        return IDRMetadata(raw_text=raw_text, rows=rows)


def rows_to_property_values(rows: Iterable[IDRRow], exclude_keys: Optional[set] = None) -> List[dict]:
    props = []
    for row in rows:
        if not row.key:
            continue
        if exclude_keys and row.key in exclude_keys:
            continue
        prop = {
            "@type": "PropertyValue",
            "name": row.key,
        }
        if row.values:
            prop["value"] = row.values
        props.append(prop)
    return props


def build_term_set_map(term_sources: Dict[str, str]) -> Dict[str, str]:
    term_set_map: Dict[str, str] = {}
    for name, uri in term_sources.items():
        name_clean = name.strip()
        uri_clean = normalize_url(uri)
        if not name_clean or not uri_clean:
            continue
        if uri_clean.rstrip("/").endswith("/obo"):
            term_set_id = f"https://www.ebi.ac.uk/ols/ontologies/{name_clean.lower()}"
        else:
            term_set_id = uri_clean
        term_set_map[name_clean] = term_set_id
    return term_set_map


def add_term_sets(graph: GraphBuilder, term_set_map: Dict[str, str]) -> None:
    for name, term_set_id in term_set_map.items():
        if not term_set_id:
            continue
        graph.add(
            {
                "@id": term_set_id,
                "@type": "DefinedTermSet",
                "name": name,
                "url": term_set_id,
            }
        )


def build_defined_term(
    name: Optional[str],
    accession: Optional[str],
    source_ref: Optional[str],
    term_sources: Dict[str, str],
    term_set_map: Dict[str, str],
    fallback_prefix: str,
) -> Tuple[str, dict]:
    term_id = build_term_id(accession, source_ref, term_sources)
    if term_id == "#term":
        label = name or accession or "term"
        term_id = f"#{fallback_prefix}-{slugify(label)}"
    term_entity = {
        "@id": term_id,
        "@type": "DefinedTerm",
        "name": name or accession or term_id,
    }
    if accession:
        term_entity["identifier"] = accession
        term_entity["termCode"] = accession
    if source_ref:
        source_id = get_term_set_id(term_set_map, source_ref)
        if source_id:
            term_entity["inDefinedTermSet"] = {"@id": normalize_url(source_id)}
    return term_id, term_entity


def get_term_set_id(term_set_map: Dict[str, str], source_ref: Optional[str]) -> Optional[str]:
    if not source_ref:
        return None
    key = source_ref.strip()
    if not key:
        return None
    if key in term_set_map:
        return term_set_map[key]
    key_lower = key.lower()
    for name, term_set_id in term_set_map.items():
        if name.lower() == key_lower:
            return term_set_id
    return None




def rows_from_property_values(properties: Optional[Iterable], entity_map: Dict[str, dict]) -> List[IDRRow]:
    rows: List[IDRRow] = []
    for prop in as_list(properties):
        prop_entity = prop
        if isinstance(prop, dict) and prop.get("@id") and len(prop) == 1:
            prop_entity = entity_map.get(prop["@id"], prop)
        if not isinstance(prop_entity, dict):
            continue
        name = prop_entity.get("name")
        if not name:
            continue
        values = prop_entity.get("value", [])
        if isinstance(values, list):
            value_list = [str(value) for value in values]
        elif values is None:
            value_list = []
        else:
            value_list = [str(values)]
        rows.append(IDRRow(key=name, values=value_list, line_no=0, section=None))
    return rows


def find_root_entity(entity_map: Dict[str, dict]) -> Optional[dict]:
    descriptor = entity_map.get("ro-crate-metadata.json")
    if descriptor and isinstance(descriptor.get("about"), dict):
        root_id = descriptor["about"].get("@id")
        if root_id and root_id in entity_map:
            return entity_map[root_id]
    return entity_map.get("./")


def resolve_entity(ref, entity_map: Dict[str, dict]) -> Optional[dict]:
    if isinstance(ref, dict) and "@id" in ref:
        return entity_map.get(ref["@id"])
    if isinstance(ref, str):
        return entity_map.get(ref)
    return None


def as_list(value) -> List:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        return value
    return f"http://{value}"


def normalize_doi(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    value = value.replace("doi:", "").strip()
    if "doi.org" in value:
        return value.replace("http://", "https://")
    if value.startswith("http://dx.doi.org/"):
        return value.replace("http://dx.doi.org/", "https://doi.org/")
    if value.startswith("https://dx.doi.org/"):
        return value.replace("https://dx.doi.org/", "https://doi.org/")
    if re.match(r"^https?://", value):
        return value
    return f"https://doi.org/{value}"


def build_root_id(accession: Optional[str], external_url: Optional[str]) -> str:
    if accession:
        accession = accession.strip()
        if accession:
            return f"https://idr.openmicroscopy.org/study/{accession}/"
    if external_url:
        return normalize_url(external_url)
    return "./"


def get_term_source_uri(term_sources: Dict[str, str], source_ref: Optional[str]) -> Optional[str]:
    if not source_ref:
        return None
    key = source_ref.strip()
    if not key:
        return None
    if key in term_sources:
        return term_sources[key]
    key_lower = key.lower()
    for name, uri in term_sources.items():
        if name.lower() == key_lower:
            return uri
    return None


def build_term_id(
    accession: Optional[str],
    source_ref: Optional[str],
    sources: Dict[str, str],
) -> str:
    if accession:
        accession = accession.strip()
        if re.match(r"^https?://", accession):
            return accession
    if source_ref:
        base = get_term_source_uri(sources, source_ref)
        if base and accession:
            return f"{base.rstrip('/')}/{accession}"
    if accession:
        return f"#{accession}"
    return "#term"






def clean_value(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("#"):
        return ""
    return stripped


def trim_trailing_empty(values: List[str]) -> List[str]:
    trimmed = list(values)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "term"


def parse_people(study_rows: List[IDRRow]) -> List[dict]:
    last_names = values_for_key(study_rows, "Study Person Last Name")
    first_names = values_for_key(study_rows, "Study Person First Name")
    emails = values_for_key(study_rows, "Study Person Email")
    addresses = values_for_key(study_rows, "Study Person Address")
    orcids = values_for_key(study_rows, "Study Person ORCID")
    roles = values_for_key(study_rows, "Study Person Roles")

    max_len = max(len(last_names), len(first_names), len(emails), len(addresses), len(orcids), len(roles), 0)
    people = []
    for idx in range(max_len):
        last_name = last_names[idx] if idx < len(last_names) else ""
        first_name = first_names[idx] if idx < len(first_names) else ""
        email = emails[idx] if idx < len(emails) else ""
        address = addresses[idx] if idx < len(addresses) else ""
        orcid = orcids[idx] if idx < len(orcids) else ""

        if not any([last_name, first_name, email, address, orcid]):
            continue

        person_id = build_orcid_id(orcid) if orcid else f"#person-{idx + 1}"
        name = " ".join([part for part in [first_name, last_name] if part]).strip() or person_id
        person = {
            "@id": person_id,
            "@type": "Person",
            "name": name,
        }
        if first_name:
            person["givenName"] = first_name
        if last_name:
            person["familyName"] = last_name
        if email:
            person["email"] = email
        if address:
            person["address"] = address
        people.append(person)
    return people


def build_orcid_id(orcid: str) -> str:
    orcid = orcid.strip()
    if not orcid:
        return orcid
    if "orcid.org" in orcid:
        return orcid
    return f"https://orcid.org/{orcid}"


def build_publication(study_rows: List[IDRRow]) -> Optional[dict]:
    doi = values_for_key(study_rows, "Study DOI")
    pubmed = values_for_key(study_rows, "Study PubMed ID")
    pmc = values_for_key(study_rows, "Study PMC ID")
    title = first_value(study_rows, "Study Publication Title")

    identifiers: List[str] = []
    pub_id = None
    if doi and doi[0].strip():
        pub_id = normalize_doi(doi[0])
        identifiers.append(pub_id)
    if pubmed and pubmed[0].strip():
        identifiers.append(f"https://pubmed.ncbi.nlm.nih.gov/{pubmed[0].strip()}/")
        if not pub_id:
            pub_id = identifiers[-1]
    if pmc and pmc[0].strip():
        identifiers.append(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc[0].strip()}/")
        if not pub_id:
            pub_id = identifiers[-1]

    if not pub_id:
        return None

    publication = {
        "@id": pub_id,
        "@type": "ScholarlyArticle",
        "name": title or pub_id,
        "identifier": identifiers if len(identifiers) > 1 else identifiers[0],
    }
    return publication


def values_for_key(rows: List[IDRRow], key: str) -> List[str]:
    for row in rows:
        if row.key == key:
            return row.values
    return []


def first_value(rows: List[IDRRow], key: str) -> Optional[str]:
    for row in rows:
        if row.key != key:
            continue
        for value in row.values:
            if value.strip():
                return value.strip()
    return None


def find_blocks(rows: List[IDRRow], start_key: str, stop_keys: List[str]) -> List[List[IDRRow]]:
    blocks: List[List[IDRRow]] = []
    current: Optional[List[IDRRow]] = None
    for row in rows:
        if row.key in stop_keys and row.has_value():
            if current:
                blocks.append(current)
            current = None
            continue
        if row.key == start_key and row.has_value():
            if current:
                blocks.append(current)
            current = []
        if current is not None:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks


def first_value_in_block(block: List[IDRRow], key: str) -> Optional[str]:
    for row in block:
        if row.key != key:
            continue
        for value in row.values:
            if value.strip():
                return value.strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert between IDR metadata text and RO-Crate 1.2 JSON-LD.")
    parser.add_argument("input", help="Path to IDR metadata text or RO-Crate JSON-LD")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path (defaults to ro-crate-metadata.json or idr-metadata.txt)",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Convert RO-Crate JSON-LD back to IDR metadata text",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Text encoding for the input file (default: utf-8)",
    )
    args = parser.parse_args()

    if args.reverse:
        output_path = Path(args.output or "idr-metadata.txt")
        metadata = ROCrateDecoder(encoding=args.encoding).decode_path(Path(args.input))
        idr_text = IDREncoder().encode(metadata)
        output_path.write_text(idr_text, encoding=args.encoding)
        return

    output_path = Path(args.output or "ro-crate-metadata.json")
    decoder = IDRDecoder(encoding=args.encoding)
    metadata = decoder.decode(Path(args.input))
    crate = ROCrateEncoder().encode(metadata)
    output_path.write_text(json.dumps(crate, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
