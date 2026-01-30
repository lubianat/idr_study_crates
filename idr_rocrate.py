#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_TERM_BASES = {
    "efo": "http://www.ebi.ac.uk/efo/",
    "ncbitaxon": "http://purl.obolibrary.org/obo/",
    "cmpo": "http://purl.obolibrary.org/obo/",
    "fbbi": "http://purl.obolibrary.org/obo/",
    "pato": "http://purl.obolibrary.org/obo/",
    "go": "http://purl.obolibrary.org/obo/",
}

DEFAULT_OLS_SOURCES = set(DEFAULT_TERM_BASES.keys())
IDR_PROFILE_ID = "https://idr.openmicroscopy.org/ro-crate/profile/0.1"
IDR_PROFILE_NAME = "IDR study metadata RO-Crate profile"
IDR_PROFILE_VERSION = "0.1.0"


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

    def first_value(
        self, key: str, rows: Optional[List[IDRRow]] = None
    ) -> Optional[str]:
        for row in rows or self.rows:
            if row.key != key:
                continue
            for value in row.values:
                if value.strip():
                    return value.strip()
        return None

    def values_for_key(
        self, key: str, rows: Optional[List[IDRRow]] = None
    ) -> List[str]:
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
    def __init__(
        self, encoding: str = "utf-8", fallback_encodings: Optional[List[str]] = None
    ) -> None:
        self.encoding = encoding
        fallback_encodings = fallback_encodings or [
            "utf-8",
            "utf-8-sig",
            "cp1252",
            "latin-1",
        ]
        self.fallback_encodings = [encoding] + [
            enc for enc in fallback_encodings if enc != encoding
        ]

    def decode(self, path: Path) -> IDRMetadata:
        raw_bytes = path.read_bytes()
        raw_text = self._decode_bytes(raw_bytes)
        return self.decode_text(raw_text)

    def decode_text(self, raw_text: str) -> IDRMetadata:
        rows = self._parse_text(raw_text)
        return IDRMetadata(raw_text=raw_text, rows=rows)

    def _decode_bytes(self, raw_bytes: bytes) -> str:
        for encoding in self.fallback_encodings:
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode(self.fallback_encodings[-1], errors="replace")

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
            rows.append(
                IDRRow(key=key, values=values, line_no=line_no, section=current_section)
            )
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
    """Encoder that generates GIDE-compliant RO-Crate from IDR metadata."""

    def _load_gide_context(self) -> dict:
        """Load the GIDE context from the JSON-LD file."""
        context_path = Path(__file__).resolve().parent / "gide-search-context.jsonld"
        if context_path.exists():
            try:
                data = json.loads(context_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "@context" in data:
                    return data["@context"]
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                pass
        # Fallback GIDE context
        return {
            "bia": "https://bioimage-archive.org/ro-crate/",
            "obo": "http://purl.obolibrary.org/obo/",
            "dwc": "http://rs.tdwg.org/dwc/terms/",
            "dwciri": "http://rs.tdwg.org/dwc/iri/",
            "bao": "http://www.bioassayontology.org/bao#",
            "vernacularName": {"@id": "dwc:vernacularName"},
            "scientificName": {"@id": "dwc:scientificName"},
            "Taxon": {"@id": "dwc:Taxon"},
            "hasCellLine": {"@id": "bao:BAO_0002004"},
            "measurementMethod": {"@id": "dwciri:measurementMethod", "@type": "@id"},
            "taxonomicRange": {
                "@id": "http://schema.org/taxonomicRange",
                "@type": "@id",
            },
            "seeAlso": {"@id": "rdf:seeAlso", "@type": "@id"},
            "BioSample": {"@id": "http://schema.org/BioSample"},
            "LabProtocol": {"@id": "http://schema.org/LabProtocol"},
            "labEquipment": {"@id": "http://schema.org/labEquipment"},
        }

    def encode(self, metadata: IDRMetadata) -> dict:
        graph = GraphBuilder()
        gide_context = self._load_gide_context()
        context = [
            "https://w3id.org/ro/crate/1.2/context",
            gide_context,
        ]

        study_rows, _ = metadata.split_study_rows()
        term_sources = metadata.term_source_map()
        accession = metadata.first_value("Comment[IDR Study Accession]", study_rows)
        study_external_url = metadata.first_value("Study External URL", study_rows)
        root_id = build_root_id(accession, study_external_url)

        # RO-Crate Metadata Descriptor
        graph.add(
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
                "about": {"@id": root_id},
            }
        )

        # Add Dataset placeholder early so it appears right after CreativeWork
        # It will be updated with full properties later
        graph.add({"@id": root_id, "@type": "Dataset"})

        # Publisher entity
        graph.add(
            {
                "@id": "https://idr.openmicroscopy.org/",
                "@type": "Organization",
                "name": "Image Data Resource",
                "url": "https://idr.openmicroscopy.org/",
            }
        )

        # Parse authors
        people = parse_people(study_rows)
        for person in people:
            graph.add(person)

        # Publication entity
        publication = self._build_publication_gide(study_rows)
        if publication:
            graph.add(publication)

        # Taxon entities from Study Organism
        taxon_refs = []
        organism_values = metadata.values_for_key("Study Organism", study_rows)
        organism_accessions = metadata.values_for_key(
            "Study Organism Term Accession", study_rows
        )
        for idx, org_name in enumerate(organism_values):
            if not org_name.strip():
                continue
            accession_value = (
                organism_accessions[idx] if idx < len(organism_accessions) else ""
            )
            taxon_id = self._build_taxon_id(accession_value, org_name, term_sources)
            taxon_entity = {
                "@id": taxon_id,
                "@type": "Taxon",
                "scientificName": org_name.strip(),
            }
            graph.add(taxon_entity)
            taxon_refs.append({"@id": taxon_id})

        # Process screens and experiments
        screen_blocks = find_blocks(
            metadata.rows, "Screen Number", stop_keys=["Experiment Number"]
        )
        experiment_blocks = find_blocks(
            metadata.rows, "Experiment Number", stop_keys=["Screen Number"]
        )

        # Build BioSamples
        biosample_refs = []
        all_protocol_refs = []
        all_imaging_refs = []
        all_imaging_protocol_refs = []

        for idx, block in enumerate(screen_blocks, start=1):
            sample_type = first_value_in_block(block, "Screen Sample Type") or "cell"
            description = first_value_in_block(block, "Screen Description") or ""
            biosample_id = f"#screen-biosample-{idx}"
            biosample = {
                "@id": biosample_id,
                "@type": "BioSample",
                "name": sample_type,
                "description": description,
            }
            if taxon_refs:
                biosample["taxonomicRange"] = taxon_refs
            graph.add(biosample)
            biosample_refs.append({"@id": biosample_id})

            # Imaging method
            imaging_method = first_value_in_block(block, "Screen Imaging Method")
            imaging_accession = first_value_in_block(
                block, "Screen Imaging Method Term Accession"
            )
            if imaging_method or imaging_accession:
                imaging_id = self._build_term_id_simple(imaging_accession, term_sources)
                imaging_entity = {
                    "@id": imaging_id,
                    "@type": "DefinedTerm",
                    "name": imaging_method or imaging_accession,
                }
                graph.add(imaging_entity)
                all_imaging_refs.append({"@id": imaging_id})

                # Create an imaging protocol (protocol-0) that links to the FBbi term
                imaging_protocol_id = f"#screen-protocol-{idx}-0"
                imaging_protocol = {
                    "@id": imaging_protocol_id,
                    "@type": "LabProtocol",
                    "name": imaging_method or imaging_accession,
                    "measurementTechnique": [{"@id": imaging_id}],
                }
                graph.add(imaging_protocol)
                all_imaging_protocol_refs.append({"@id": imaging_protocol_id})

                # Build LabProtocols for this screen
                protocol_refs = self._build_lab_protocols(
                    block, idx, imaging_id, graph, "screen", term_sources
                )
                all_protocol_refs.extend(protocol_refs)

        for idx, block in enumerate(experiment_blocks, start=1):
            sample_type = (
                first_value_in_block(block, "Experiment Sample Type") or "tissue"
            )
            description = first_value_in_block(block, "Experiment Description") or ""
            biosample_id = f"#experiment-biosample-{idx}"
            biosample = {
                "@id": biosample_id,
                "@type": "BioSample",
                "name": sample_type,
                "description": description,
            }
            if taxon_refs:
                biosample["taxonomicRange"] = taxon_refs
            graph.add(biosample)
            biosample_refs.append({"@id": biosample_id})

            # Imaging method
            imaging_method = first_value_in_block(block, "Experiment Imaging Method")
            imaging_accession = first_value_in_block(
                block, "Experiment Imaging Method Term Accession"
            )
            if imaging_method or imaging_accession:
                imaging_id = self._build_term_id_simple(imaging_accession, term_sources)
                imaging_entity = {
                    "@id": imaging_id,
                    "@type": "DefinedTerm",
                    "name": imaging_method or imaging_accession,
                }
                graph.add(imaging_entity)
                all_imaging_refs.append({"@id": imaging_id})

                # Create an imaging protocol (protocol-0) that links to the FBbi term
                imaging_protocol_id = f"#experiment-protocol-{idx}-0"
                imaging_protocol = {
                    "@id": imaging_protocol_id,
                    "@type": "LabProtocol",
                    "name": imaging_method or imaging_accession,
                    "measurementTechnique": [{"@id": imaging_id}],
                }
                graph.add(imaging_protocol)
                all_imaging_protocol_refs.append({"@id": imaging_protocol_id})

                # Build LabProtocols for this experiment
                protocol_refs = self._build_lab_protocols(
                    block, idx, imaging_id, graph, "experiment", term_sources
                )
                all_protocol_refs.extend(protocol_refs)

        # Dataset size
        size_refs = self._build_dataset_size(screen_blocks, experiment_blocks, graph)

        # Root Dataset entity
        root = {"@id": root_id, "@type": "Dataset"}

        # name
        title = metadata.first_value("Study Title", study_rows)
        root["name"] = title or accession or root_id

        # description
        description = metadata.first_value("Study Description", study_rows)
        root["description"] = description or title or root_id

        # datePublished
        pub_date = metadata.first_value("Study Public Release Date", study_rows)
        if pub_date:
            root["datePublished"] = pub_date

        # license
        license_url = metadata.first_value("Study License URL", study_rows)
        if license_url:
            root["license"] = normalize_url(license_url)

        # identifier
        if accession:
            root["identifier"] = accession

        # publisher
        root["publisher"] = {"@id": "https://idr.openmicroscopy.org/"}

        # author
        if people:
            root["author"] = [{"@id": person["@id"]} for person in people]

        # seeAlso (publication)
        if publication:
            root["seeAlso"] = [{"@id": publication["@id"]}]

        # about (BioSamples and Taxa)
        about_refs = biosample_refs + taxon_refs
        if about_refs:
            root["about"] = about_refs

        # measurementMethod (imaging protocols first, then other protocols, then imaging methods)
        measurement_refs = (
            all_imaging_protocol_refs + all_protocol_refs + all_imaging_refs
        )
        measurement_refs = self._dedupe_refs(measurement_refs)
        if measurement_refs:
            root["measurementMethod"] = measurement_refs

        # thumbnailUrl - get all values from the row, not just the first
        thumbnails = []
        for block in screen_blocks:
            for row in block:
                if row.key == "Screen Example Images":
                    for val in row.values:
                        thumbnails.extend(self._extract_urls(val))
        for block in experiment_blocks:
            for row in block:
                if row.key == "Experiment Example Images":
                    for val in row.values:
                        thumbnails.extend(self._extract_urls(val))
        if thumbnails:
            root["thumbnailUrl"] = thumbnails

        # size
        if size_refs:
            root["size"] = size_refs

        graph.add(root)
        return {"@context": context, "@graph": graph.to_list()}

    def _build_publication_gide(self, study_rows: List[IDRRow]) -> Optional[dict]:
        """Build a ScholarlyArticle entity for GIDE format."""
        doi = first_value(study_rows, "Study DOI")
        title = first_value(study_rows, "Study Publication Title")

        if not doi:
            return None

        pub_id = normalize_doi(doi)
        return {
            "@id": pub_id,
            "@type": "ScholarlyArticle",
            "name": title or pub_id,
        }

    def _build_taxon_id(
        self, accession: str, name: str, term_sources: Dict[str, str]
    ) -> str:
        """Build a taxon ID from NCBITaxon accession."""
        accession = accession.strip() if accession else ""
        if accession:
            # Handle NCBITaxon format
            match = re.search(
                r"(?:NCBITaxon[_:]?)(\d+)", accession, flags=re.IGNORECASE
            )
            if match:
                return f"http://purl.obolibrary.org/obo/NCBITaxon_{match.group(1)}"
            if accession.isdigit():
                return f"http://purl.obolibrary.org/obo/NCBITaxon_{accession}"
            if re.match(r"^https?://", accession):
                return accession
        # Fallback to fragment ID
        return f"#taxon-{slugify(name)}"

    def _build_term_id_simple(
        self, accession: Optional[str], term_sources: Dict[str, str]
    ) -> str:
        """Build a term ID from an ontology accession."""
        if not accession:
            return "#term"
        accession = accession.strip()
        if re.match(r"^https?://", accession):
            return accession
        # Try to resolve common ontology prefixes
        match = re.match(r"^([A-Za-z]+)[_:](\d+)$", accession)
        if match:
            prefix = match.group(1).upper()
            number = match.group(2)
            return f"http://purl.obolibrary.org/obo/{prefix}_{number}"
        return f"#{accession}"

    def _build_lab_protocols(
        self,
        block: List[IDRRow],
        block_idx: int,
        imaging_id: str,
        graph: GraphBuilder,
        prefix: str,
        term_sources: Dict[str, str],
    ) -> List[dict]:
        """Build LabProtocol entities from protocol fields in a block."""
        protocol_refs = []

        # Get protocol names and descriptions from multi-valued fields
        protocol_names = []
        protocol_descriptions = []
        protocol_types = []
        protocol_type_accessions = []
        protocol_type_source_refs = []
        for row in block:
            if row.key == "Protocol Name":
                protocol_names = [v.strip() for v in row.values if v.strip()]
            elif row.key == "Protocol Description":
                protocol_descriptions = [v.strip() for v in row.values if v.strip()]
            elif row.key == "Protocol Type":
                protocol_types = [v.strip() for v in row.values]
            elif row.key == "Protocol Type Term Accession":
                protocol_type_accessions = [v.strip() for v in row.values]
            elif row.key == "Protocol Type Term Source REF":
                protocol_type_source_refs = [v.strip() for v in row.values]

        # Create LabProtocol entities for each protocol
        for protocol_counter, name in enumerate(protocol_names, start=1):
            idx = protocol_counter - 1
            description = (
                protocol_descriptions[idx] if idx < len(protocol_descriptions) else ""
            )
            protocol_id = f"#{prefix}-protocol-{block_idx}-{protocol_counter}"
            protocol = {
                "@id": protocol_id,
                "@type": "LabProtocol",
                "name": name,
                "description": description or name,
            }

            # Use EFO protocol type term as measurementTechnique if available
            if idx < len(protocol_type_accessions) and protocol_type_accessions[idx]:
                accession = protocol_type_accessions[idx]
                source_ref = (
                    protocol_type_source_refs[idx]
                    if idx < len(protocol_type_source_refs)
                    else None
                )
                type_id = self._build_term_id_with_source(
                    accession, source_ref, term_sources
                )
                if type_id:
                    # Add DefinedTerm entity for the protocol type
                    type_name = (
                        protocol_types[idx]
                        if idx < len(protocol_types) and protocol_types[idx]
                        else name
                    )
                    graph.add(
                        {
                            "@id": type_id,
                            "@type": "DefinedTerm",
                            "name": type_name,
                        }
                    )
                    protocol["measurementTechnique"] = [{"@id": type_id}]

            # Fallback to imaging method if no protocol type term
            if "measurementTechnique" not in protocol:
                protocol["measurementTechnique"] = [{"@id": imaging_id}]

            graph.add(protocol)
            protocol_refs.append({"@id": protocol_id})

        return protocol_refs

    def _build_term_id_with_source(
        self, accession: str, source_ref: Optional[str], term_sources: Dict[str, str]
    ) -> Optional[str]:
        """Build a term ID from an ontology accession and source reference."""
        if not accession:
            return None
        accession = accession.strip()
        if re.match(r"^https?://", accession):
            return accession

        # Try to use the source reference to determine the base URI
        if source_ref:
            source_ref_lower = source_ref.lower()
            if source_ref_lower in term_sources:
                base = term_sources[source_ref_lower]
                # Handle cases like "EFO_0003789" -> use as-is
                return f"{base}{accession}"
            # Check DEFAULT_TERM_BASES
            if source_ref_lower in DEFAULT_TERM_BASES:
                base = DEFAULT_TERM_BASES[source_ref_lower]
                return f"{base}{accession}"

        # Fallback: try to resolve common ontology prefixes from accession
        match = re.match(r"^([A-Za-z]+)[_:](\d+)$", accession)
        if match:
            prefix = match.group(1).lower()
            number = match.group(2)
            if prefix in DEFAULT_TERM_BASES:
                base = DEFAULT_TERM_BASES[prefix]
                return f"{base}{prefix.upper()}_{number}"
            # Default OBO format
            return f"http://purl.obolibrary.org/obo/{match.group(1).upper()}_{number}"

        return None

    def _build_dataset_size(
        self,
        screen_blocks: List[List[IDRRow]],
        experiment_blocks: List[List[IDRRow]],
        graph: GraphBuilder,
    ) -> List[dict]:
        """Build QuantitativeValue entities for dataset size."""
        size_refs = []

        # Look for Screen Size or Experiment Size fields
        tb_parts = []
        images_parts = []

        for block in screen_blocks + experiment_blocks:
            for row in block:
                # Parse "Screen Size" or "Experiment Size" fields
                if row.key in ("Screen Size", "Experiment Size"):
                    for val in row.values:
                        val = val.strip()
                        # Parse "Total Tb: 10.06" format
                        tb_match = re.search(
                            r"Total\s+Tb:\s*([0-9.]+)", val, re.IGNORECASE
                        )
                        if tb_match:
                            tb_parts.append(float(tb_match.group(1)))
                        # Parse "5D Images: 109728" format
                        images_match = re.search(
                            r"5D\s+Images:\s*(\d+)", val, re.IGNORECASE
                        )
                        if images_match:
                            images_parts.append(int(images_match.group(1)))

        total_tb = sum(tb_parts)
        total_images = sum(images_parts)

        # Convert TB to bytes (1 TB = 1099511627776 bytes)
        if total_tb > 0:
            total_bytes = int(total_tb * 1099511627776)
            size_id = "#total-dataset-size"
            # Build description showing sum if multiple sources
            if len(tb_parts) > 1:
                parts_str = " + ".join(str(t) for t in tb_parts)
                desc = f"{parts_str} = {total_tb} TB"
            else:
                desc = f"{total_tb} TB"
            graph.add(
                {
                    "@id": size_id,
                    "@type": "QuantitativeValue",
                    "value": total_bytes,
                    "unitCode": "http://purl.obolibrary.org/obo/UO_0000233",
                    "unitText": "bytes",
                    "description": desc,
                }
            )
            size_refs.append({"@id": size_id})

        if total_images > 0:
            count_id = "#file-count"
            # Build description showing sum if multiple sources
            if len(images_parts) > 1:
                parts_str = " + ".join(str(i) for i in images_parts)
                desc = f"{parts_str} = {total_images} 5D images"
            else:
                desc = f"{total_images} 5D images"
            graph.add(
                {
                    "@id": count_id,
                    "@type": "QuantitativeValue",
                    "value": total_images,
                    "unitCode": "http://purl.obolibrary.org/obo/UO_0000189",
                    "unitText": "file count",
                    "description": desc,
                }
            )
            size_refs.append({"@id": count_id})

        return size_refs

    def _extract_urls(self, value: str) -> List[str]:
        """Extract URLs from a string value."""
        urls = []
        for token in re.split(r"\s+", value.strip()):
            if not token:
                continue
            candidate = token.strip(",;")
            if candidate.startswith(("http://", "https://", "www.")):
                urls.append(normalize_url(candidate))
        return urls

    def _dedupe_refs(self, refs: List[dict]) -> List[dict]:
        """Remove duplicate references by @id."""
        seen = set()
        result = []
        for ref in refs:
            ref_id = ref.get("@id")
            if ref_id and ref_id not in seen:
                seen.add(ref_id)
                result.append(ref)
        return result


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

        entity_map = {
            entity.get("@id"): entity
            for entity in graph
            if isinstance(entity, dict) and entity.get("@id")
        }
        root_entity = find_root_entity(entity_map)

        rows: List[IDRRow] = []
        if root_entity:
            rows.extend(
                rows_from_property_values(
                    root_entity.get("additionalProperty"), entity_map
                )
            )
            for part_ref in as_list(root_entity.get("hasPart")):
                part_entity = resolve_entity(part_ref, entity_map)
                if part_entity:
                    rows.extend(
                        rows_from_property_values(
                            part_entity.get("additionalProperty"), entity_map
                        )
                    )

        raw_text = IDREncoder().encode_rows(rows)
        return IDRMetadata(raw_text=raw_text, rows=rows)


def rows_to_property_values(
    rows: Iterable[IDRRow], exclude_keys: Optional[set] = None
) -> List[dict]:
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


def get_term_set_id(
    term_set_map: Dict[str, str], source_ref: Optional[str]
) -> Optional[str]:
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
    if key_lower in DEFAULT_OLS_SOURCES:
        return f"https://www.ebi.ac.uk/ols/ontologies/{key_lower}"
    return None


def rows_from_property_values(
    properties: Optional[Iterable], entity_map: Dict[str, dict]
) -> List[IDRRow]:
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
    # Handle dx.doi.org first (before the general doi.org check)
    if "dx.doi.org" in value:
        value = value.replace("http://dx.doi.org/", "https://doi.org/")
        value = value.replace("https://dx.doi.org/", "https://doi.org/")
        return value
    if "doi.org" in value:
        return value.replace("http://", "https://")
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


def get_term_source_uri(
    term_sources: Dict[str, str], source_ref: Optional[str]
) -> Optional[str]:
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
    if key_lower in DEFAULT_TERM_BASES:
        return DEFAULT_TERM_BASES[key_lower]
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

    max_len = max(
        len(last_names),
        len(first_names),
        len(emails),
        len(addresses),
        len(orcids),
        len(roles),
        0,
    )
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
        name = (
            " ".join([part for part in [first_name, last_name] if part]).strip()
            or person_id
        )
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
        identifiers.append(
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc[0].strip()}/"
        )
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


def find_blocks(
    rows: List[IDRRow], start_key: str, stop_keys: List[str]
) -> List[List[IDRRow]]:
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
    parser = argparse.ArgumentParser(
        description="Convert between IDR metadata text and RO-Crate 1.2 JSON-LD."
    )
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
    output_path.write_text(
        json.dumps(crate, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
